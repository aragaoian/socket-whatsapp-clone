import json
import shutil
import signal
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from threading import Condition, Lock, RLock, Thread

from consts.config import (
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    MAX_MISSED_ACKS,
    ORDER_RECOVERY_TIMEOUT,
)
from enums.commands import Commands
from enums.message_types import MessageType
from models.heartbeat_control import HeartbeatControl
from models.node_config import NodeConfig
from models.node_dto import NodeDto
from models.snapshot_session import SnapshotSession
from services.socket import Socket
from services.terminal import RESET_SCROLL, print_message, setup_terminal
from utils.find_node import find_node_config
from utils.formatting import (
    format_global_message,
    format_local_message,
    format_message,
    format_node_list,
    format_snapshot,
)


class Node:
    def __init__(
        self,
        id: int,
        host: str,
        port: int,
        nodes: list[NodeConfig],
        leader_id: int,
        vector_clock: list[int],
    ):
        self.id = id
        self.host = host
        self.port = port
        self.nodes = nodes
        self.leader_id = leader_id
        self.vector_clock = vector_clock
        self.vector_clock_lock = Lock()
        self.local_history_lock = Lock()
        self.sequence_lock = Lock()
        self.delivery_lock = Lock()
        self.event_lock = RLock()
        self.local_sequence = 0
        self.next_global_sequence = 1
        self.next_delivery_sequence = 1
        self.local_history: list[NodeDto] = []
        self.global_history: list[NodeDto] = []
        self.delivery_buffer: dict[int, NodeDto] = {}
        self.last_seen_control: dict[int, HeartbeatControl] = {
            node.id: HeartbeatControl(timestamp=time.monotonic())
            for node in self.nodes
            if node.id != self.id
        }
        self.heartbeat_lock = Lock()
        self.election_lock = Lock()
        self.election_in_progress = False
        self.leader_ready = True
        self.order_recovery_condition = Condition()
        self.order_recovery_id: str | None = None
        self.order_recovery_expected: set[int] = set()
        self.order_recovery_responses: dict[int, dict[str, object]] = {}
        self.pending_group_lock = Lock()
        self.pending_group_requests: list[NodeDto] = []
        self.outgoing_channel_locks: dict[int, Lock] = {
            node.id: Lock() for node in self.nodes
        }
        self.outgoing_channel_sequence: dict[int, int] = {
            node.id: 0 for node in self.nodes
        }
        self.incoming_channel_lock = Lock()
        self.incoming_next_sequence: dict[int, int] = {
            node.id: 1 for node in self.nodes
        }
        self.incoming_channel_buffers: dict[int, dict[int, NodeDto]] = {
            node.id: {} for node in self.nodes
        }
        self.snapshot_lock = Lock()
        self.snapshots: dict[str, SnapshotSession] = {}
        self.completed_snapshots: dict[str, dict[int, dict[str, object]]] = {}
        self.tcp_server = None

    def close(self) -> None:

        if self.tcp_server is not None:
            try:
                self.tcp_server.shutdown(2)
            except OSError:
                pass
            finally:
                self.tcp_server.close()
                self.tcp_server = None

    def start(self) -> None:
        setup_terminal()

        self.tcp_server = Socket.server(self.port)

        def terminate(*_args) -> None:
            self.close()

        signal.signal(signal.SIGINT, terminate)
        signal.signal(signal.SIGTERM, terminate)

        threads = [
            Thread(
                target=Socket.listen,
                args=(self.tcp_server, self.handle_message),
                daemon=True,
            ),
            Thread(
                target=self.heartbeat,
                daemon=True,
            ),
            Thread(
                target=self.health_check,
                daemon=True,
            ),
        ]

        for thread in threads:
            thread.start()

        self.tui()

    def tui(self) -> None:
        linhas = shutil.get_terminal_size().lines
        print_message(f"PORTA {self.port}")

        while True:
            sys.stdout.write(f"\033[{linhas};1H\033[2K")
            sys.stdout.flush()

            try:
                comando = input(f"{self.id}> ")

                if not self.handle_command(comando):
                    break

            except (KeyboardInterrupt, EOFError):
                sys.stdout.write(RESET_SCROLL)
                break

    def handle_command(self, command_str: str) -> bool:
        with self.event_lock:
            return self._handle_command(command_str)

    def _handle_command(self, command_str: str) -> bool:
        parts = command_str.split()
        if not parts:
            return True

        command = parts[0].lower()
        now_ = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")

        if command == Commands.SEND.value:
            if len(parts) < 3:
                print_message("Uso: send <id> <mensagem>")
                return True

            try:
                destination_node_id = int(parts[1])
            except ValueError:
                print_message("O ID de destino deve ser um número inteiro.")
                return True

            if destination_node_id == self.id:
                print_message("Escolha outro nó como destino.")
                return True

            message = " ".join(parts[2:])
            node_info = find_node_config(destination_node_id, self.nodes)
            if node_info is None:
                print_message(f"Node {destination_node_id} não encontrado.")
                return True

            dto = self.create_local_message(
                message_type=MessageType.PRIVATE_MESSAGE,
                timestamp=now_,
                message=message,
                destination=destination_node_id,
            )
            self.send_to_node(node_info, dto)
            return True

        if command == Commands.SEND_ALL.value:
            if len(parts) < 2:
                print_message("Uso: sendall <mensagem>")
                return True

            dto = self.create_local_message(
                message_type=MessageType.GROUP_MESSAGE_REQUEST,
                timestamp=now_,
                message=" ".join(parts[1:]),
            )
            self.request_group_order(dto)
            return True

        if command == Commands.LOCAL.value:
            self.show_local_history()
            return True

        if command == Commands.GLOBAL.value:
            self.show_global_history()
            return True

        if command == Commands.STATUS.value:
            with self.vector_clock_lock:
                clock = self.vector_clock.copy()
            print_message(
                f"Node {self.id} | líder {self.leader_id} | VClock {clock} | "
                f"próxima entrega global {self.next_delivery_sequence}"
            )
            self.show_local_history()
            self.show_global_history()
            return True

        if command == Commands.LIST.value:
            print_message(format_node_list(self.nodes))
            return True

        if command == Commands.SNAPSHOT.value:
            self.initiate_snapshot()
            return True

        if command == Commands.HELP.value:
            print_message(
                "Comandos: send <id> <msg>, sendall <msg>, local, global, status, "
                "list, snapshot, exit"
            )
            return True

        if command == Commands.EXIT.value:
            sys.stdout.write(RESET_SCROLL)
            print("\nPrograma encerrado.")
            return False

        return True

    def create_local_message(
        self,
        message_type: MessageType,
        timestamp: str,
        message: str,
        destination: int | None = None,
    ) -> NodeDto:
        with self.vector_clock_lock:
            self.vector_clock[self.id - 1] += 1
            vector_clock = self.vector_clock.copy()

        with self.local_history_lock:
            self.local_sequence += 1
            dto = NodeDto(
                type=message_type.value,
                origin=self.id,
                timestamp=timestamp,
                vector_clock=vector_clock,
                message=message,
                destination=destination,
                local_sequence=self.local_sequence,
            )
            self.local_history.append(dto)

        print_message(format_local_message(dto))
        return dto

    def send_to_node(self, node: NodeConfig, payload: NodeDto) -> bool:
        channel_lock = self.outgoing_channel_locks[node.id]
        with channel_lock:
            channel_sequence = self.outgoing_channel_sequence[node.id] + 1
            ordered_payload = replace(
                payload,
                channel_origin=self.id,
                channel_sequence=channel_sequence,
            )

            try:
                Socket.send(node.host, node.port, asdict(ordered_payload))
                self.outgoing_channel_sequence[node.id] = channel_sequence
                return True
            except OSError as exc:
                print_message(f"Falha ao enviar para o Node {node.id}: {exc}")
                return False

    def request_group_order(self, payload: NodeDto) -> None:
        if self.id == self.leader_id:
            self.sequence_group_message(payload)
            return

        leader = find_node_config(self.leader_id, self.nodes)
        if leader is None:
            print_message(f"Líder {self.leader_id} não encontrado.")
            return
        if not self.send_to_node(leader, payload):
            print_message("Líder não acessível, reelegendo líder.")
            self.queue_group_request(payload)
            self.update_node_status(self.leader_id)
            self.start_election()

    def queue_group_request(self, payload: NodeDto) -> None:
        with self.pending_group_lock:
            if payload not in self.pending_group_requests:
                self.pending_group_requests.append(payload)

    def retry_pending_group_requests(self) -> None:
        with self.pending_group_lock:
            pending = self.pending_group_requests.copy()
            self.pending_group_requests.clear()

        for payload in pending:
            self.request_group_order(payload)

    def start_election(self) -> None:
        with self.election_lock:
            if self.election_in_progress:
                return
            self.election_in_progress = True

        Thread(target=self.bully_election, daemon=True).start()

    def bully_election(self) -> None:
        higher_nodes = sorted(
            (node for node in self.nodes if node.id > self.id and node.is_active),
            key=lambda node: node.id,
        )

        election_message = NodeDto(
            type=MessageType.ELECTION.value,
            origin=self.id,
            timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            vector_clock=self.vector_clock.copy(),
            message="ELECTION",
        )

        higher_node_answered = False

        for node in higher_nodes:
            if self.send_to_node(node, election_message):
                higher_node_answered = True
                print_message(
                    f"[ELEIÇÃO] Node {node.id} está ativo; ele continuará a eleição."
                )

        if higher_node_answered:
            print_message("[ELEIÇÃO] Aguardando anúncio do novo coordenador.")
            return

        self.leader_id = self.id
        self.leader_ready = False
        print_message(f"[RECUPERAÇÃO] Node {self.id} reconstruindo a ordem global.")

        if not self.recover_global_order():
            print_message(
                "[RECUPERAÇÃO] Não foi possível reconstruir uma ordem consistente."
            )
            with self.election_lock:
                self.election_in_progress = False
            return

        self.leader_ready = True
        print_message(f"[COORDENADOR] Node {self.id} é o novo líder.")

        coordinator_message = NodeDto(
            type=MessageType.COORDINATOR.value,
            origin=self.id,
            timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            vector_clock=self.vector_clock.copy(),
            message="COORDINATOR",
        )

        for node in self.nodes:
            if node.id != self.id and node.is_active:
                self.send_to_node(node, coordinator_message)

        with self.election_lock:
            self.election_in_progress = False

        self.retry_pending_group_requests()

    def update_node_status(self, id: int) -> None:
        for node in self.nodes:
            if node.id != id:
                continue
            node.is_active = False

    def capture_order_state(self) -> dict[str, object]:
        with self.delivery_lock:
            return {
                "next_delivery_sequence": self.next_delivery_sequence,
                "global_history": [asdict(message) for message in self.global_history],
                "delivery_buffer": {
                    str(sequence): asdict(message)
                    for sequence, message in self.delivery_buffer.items()
                },
            }

    def recover_global_order(self) -> bool:
        recovery_id = f"{self.id}-{time.time_ns()}"
        expected = {node.id for node in self.nodes if node.is_active}
        expected.add(self.id)

        with self.order_recovery_condition:
            self.order_recovery_id = recovery_id
            self.order_recovery_expected = expected
            self.order_recovery_responses = {self.id: self.capture_order_state()}

        with self.vector_clock_lock:
            vector_clock = self.vector_clock.copy()

        for member_id in sorted(expected - {self.id}):
            node = find_node_config(member_id, self.nodes)
            if node is None:
                with self.order_recovery_condition:
                    self.order_recovery_expected.discard(member_id)
                continue

            request = NodeDto(
                type=MessageType.ORDER_STATE_REQUEST.value,
                origin=self.id,
                destination=member_id,
                timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
                vector_clock=vector_clock,
                recovery_id=recovery_id,
            )
            if not self.send_to_node(node, request):
                self.update_node_status(member_id)
                with self.order_recovery_condition:
                    self.order_recovery_expected.discard(member_id)

        with self.order_recovery_condition:
            self.order_recovery_condition.wait_for(
                lambda: self.order_recovery_expected.issubset(
                    self.order_recovery_responses
                ),
                timeout=ORDER_RECOVERY_TIMEOUT,
            )
            missing = (
                self.order_recovery_expected - self.order_recovery_responses.keys()
            )
            states = self.order_recovery_responses.copy()
            self.order_recovery_id = None
            self.order_recovery_expected = set()
            self.order_recovery_responses = {}

        for member_id in missing:
            self.update_node_status(member_id)
            print_message(
                f"[RECUPERAÇÃO] Node {member_id} não respondeu e foi inativado."
            )

        known_messages: dict[int, NodeDto] = {}
        for state in states.values():
            raw_messages = list(state["global_history"])
            raw_messages.extend(state["delivery_buffer"].values())
            for raw_message in raw_messages:
                message = NodeDto(**raw_message)
                sequence = message.global_sequence
                if sequence is None:
                    continue

                existing = known_messages.get(sequence)
                if existing is not None and self.order_message_identity(
                    existing
                ) != self.order_message_identity(message):
                    print_message(
                        f"[RECUPERAÇÃO] Conflito na sequência global {sequence}."
                    )
                    return False
                known_messages[sequence] = message

        last_sequence = 0
        while last_sequence + 1 in known_messages:
            last_sequence += 1
        if any(sequence > last_sequence for sequence in known_messages):
            print_message("[RECUPERAÇÃO] Histórico global contém uma lacuna.")
            return False

        for sequence in range(1, last_sequence + 1):
            recovered = replace(
                known_messages[sequence],
                type=MessageType.ORDERED_GROUP_MESSAGE.value,
                destination=None,
                channel_origin=None,
                channel_sequence=None,
            )
            for node in self.nodes:
                if not node.is_active:
                    continue
                if node.id == self.id:
                    self.receive_ordered_message(recovered)
                elif not self.send_to_node(node, recovered):
                    self.update_node_status(node.id)

        with self.sequence_lock:
            self.next_global_sequence = last_sequence + 1

        print_message(
            f"[RECUPERAÇÃO] Ordem restaurada até {last_sequence}; "
            f"próxima sequência {self.next_global_sequence}."
        )
        return True

    @staticmethod
    def order_message_identity(message: NodeDto) -> tuple[object, ...]:
        return (
            message.origin,
            message.local_sequence,
            message.timestamp,
            tuple(message.vector_clock),
            message.message,
        )

    def handle_order_state_request(self, payload: NodeDto) -> None:
        if payload.recovery_id is None:
            raise ValueError("Pedido de recuperação sem identificador")

        requester = find_node_config(payload.origin, self.nodes)
        if requester is None:
            return

        with self.vector_clock_lock:
            vector_clock = self.vector_clock.copy()
        response = NodeDto(
            type=MessageType.ORDER_STATE_RESPONSE.value,
            origin=self.id,
            destination=payload.origin,
            timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            vector_clock=vector_clock,
            recovery_id=payload.recovery_id,
            order_state=self.capture_order_state(),
        )
        self.send_to_node(requester, response)

    def handle_order_state_response(self, payload: NodeDto) -> None:
        if payload.recovery_id is None or payload.order_state is None:
            raise ValueError("Resposta de recuperação incompleta")

        with self.order_recovery_condition:
            if payload.recovery_id != self.order_recovery_id:
                return
            if payload.origin not in self.order_recovery_expected:
                return

            self.order_recovery_responses[payload.origin] = payload.order_state
            self.order_recovery_condition.notify_all()

    def sequence_group_message(self, payload: NodeDto) -> None:
        if self.id != self.leader_id:
            return
        if not self.leader_ready:
            self.queue_group_request(payload)
            print_message("Recuperação da ordem em andamento; mensagem enfileirada.")
            return

        with self.sequence_lock:
            global_sequence = self.next_global_sequence
            self.next_global_sequence += 1

        ordered_payload = replace(
            payload,
            type=MessageType.ORDERED_GROUP_MESSAGE.value,
            destination=None,
            global_sequence=global_sequence,
            vector_clock=payload.vector_clock.copy(),
        )

        for node in self.nodes:
            if node.id == self.id:
                self.receive_ordered_message(ordered_payload)
            else:
                self.send_to_node(node, ordered_payload)

    def receive_ordered_message(self, payload: NodeDto) -> None:
        sequence = payload.global_sequence
        if sequence is None:
            print_message("Mensagem de grupo recebida sem sequência global.")
            return

        with self.delivery_lock:
            if sequence < self.next_delivery_sequence:
                return
            self.delivery_buffer.setdefault(sequence, payload)

            while self.next_delivery_sequence in self.delivery_buffer:
                next_payload = self.delivery_buffer.pop(self.next_delivery_sequence)
                self.handle_vector_clock(next_payload.vector_clock)
                self.global_history.append(next_payload)
                self.next_delivery_sequence += 1
                print_message(format_global_message(next_payload))

    def show_local_history(self) -> None:
        with self.local_history_lock:
            history = self.local_history.copy()

        print_message("--- ORDEM LOCAL ---")
        if not history:
            print_message("(nenhum envio local)")
        for payload in history:
            print_message(format_local_message(payload))

    def show_global_history(self) -> None:
        with self.delivery_lock:
            history = self.global_history.copy()
            buffered = sorted(self.delivery_buffer)

        print_message("--- ORDEM GLOBAL ---")
        if not history:
            print_message("(nenhuma mensagem de grupo entregue)")
        for payload in history:
            print_message(format_global_message(payload))
        if buffered:
            print_message(f"Aguardando no buffer: {buffered}")

    def capture_local_state(self) -> dict[str, object]:
        with (
            self.delivery_lock,
            self.vector_clock_lock,
            self.local_history_lock,
            self.sequence_lock,
        ):
            return {
                "node_id": self.id,
                "leader_id": self.leader_id,
                "vector_clock": self.vector_clock.copy(),
                "local_sequence": self.local_sequence,
                "next_global_sequence": self.next_global_sequence,
                "next_delivery_sequence": self.next_delivery_sequence,
                "local_history": [asdict(message) for message in self.local_history],
                "global_history": [asdict(message) for message in self.global_history],
                "delivery_buffer": {
                    str(sequence): asdict(message)
                    for sequence, message in self.delivery_buffer.items()
                },
                "active_nodes": sorted(
                    node.id for node in self.nodes if node.is_active
                ),
            }

    def initiate_snapshot(self) -> str:
        with self.event_lock:
            snapshot_id = f"{self.id}-{time.time_ns()}"
            members = {node.id for node in self.nodes if node.is_active}
            members.add(self.id)

            with self.snapshot_lock:
                self.snapshots[snapshot_id] = SnapshotSession(
                    snapshot_id=snapshot_id,
                    initiator_id=self.id,
                    members=members,
                    local_state=self.capture_local_state(),
                    recording_channels=members - {self.id},
                    channel_states={
                        node_id: [] for node_id in members if node_id != self.id
                    },
                )

            print_message(
                f"[SNAPSHOT {snapshot_id}] Estado local registrado; "
                f"aguardando {len(members) - 1} nó(s)."
            )
            self.send_snapshot_markers(snapshot_id, self.id, members)
            self.finish_snapshot_if_ready(snapshot_id)
            return snapshot_id

    def send_snapshot_markers(
        self,
        snapshot_id: str,
        initiator_id: int,
        members: set[int],
    ) -> None:
        with self.vector_clock_lock:
            vector_clock = self.vector_clock.copy()

        for member_id in sorted(members):
            if member_id == self.id:
                continue

            node = find_node_config(member_id, self.nodes)
            if node is None:
                continue

            marker = NodeDto(
                type=MessageType.SNAPSHOT_MARKER.value,
                origin=self.id,
                destination=member_id,
                timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
                vector_clock=vector_clock,
                snapshot_id=snapshot_id,
                snapshot_initiator=initiator_id,
                snapshot_members=sorted(members),
            )
            if not self.send_to_node(node, marker):
                print_message(
                    f"[SNAPSHOT {snapshot_id}] Não foi possível enviar marcador "
                    f"ao Node {member_id}."
                )

    def handle_snapshot_marker(self, payload: NodeDto) -> None:
        snapshot_id = payload.snapshot_id
        if (
            snapshot_id is None
            or payload.snapshot_initiator is None
            or payload.snapshot_members is None
        ):
            raise ValueError("Marcador de snapshot incompleto")

        members = set(payload.snapshot_members)
        if self.id not in members or payload.origin not in members:
            raise ValueError("Membros incompatíveis no marcador de snapshot")

        first_marker = False
        with self.snapshot_lock:
            session = self.snapshots.get(snapshot_id)
            if session is None:
                first_marker = True
                session = SnapshotSession(
                    snapshot_id=snapshot_id,
                    initiator_id=payload.snapshot_initiator,
                    members=members,
                    local_state=self.capture_local_state(),
                    recording_channels=members - {self.id, payload.origin},
                    channel_states={
                        node_id: [] for node_id in members if node_id != self.id
                    },
                )
                self.snapshots[snapshot_id] = session
            else:
                session.recording_channels.discard(payload.origin)

        if first_marker:
            print_message(
                f"[SNAPSHOT {snapshot_id}] Primeiro marcador recebido do "
                f"Node {payload.origin}; estado local registrado."
            )
            self.send_snapshot_markers(
                snapshot_id,
                payload.snapshot_initiator,
                members,
            )

        self.finish_snapshot_if_ready(snapshot_id)

    def record_snapshot_message(self, payload: NodeDto) -> None:
        message_state = asdict(payload)
        channel_origin = payload.channel_origin or payload.origin
        with self.snapshot_lock:
            for session in self.snapshots.values():
                if session.reported:
                    continue
                if channel_origin in session.recording_channels:
                    session.channel_states[channel_origin].append(message_state)

    def snapshot_report(self, session: SnapshotSession) -> dict[str, object]:
        return {
            "node_id": self.id,
            "local_state": session.local_state,
            "channel_states": {
                str(origin): messages
                for origin, messages in session.channel_states.items()
            },
        }

    def finish_snapshot_if_ready(self, snapshot_id: str) -> None:
        report: dict[str, object] | None = None
        initiator_id: int | None = None
        completed_reports: dict[int, dict[str, object]] | None = None

        with self.snapshot_lock:
            session = self.snapshots[snapshot_id]
            if session.recording_channels or session.reported:
                return

            session.reported = True
            report = self.snapshot_report(session)
            initiator_id = session.initiator_id

            if initiator_id == self.id:
                session.reports[self.id] = report
                completed_reports = self.complete_snapshot_if_ready(session)

        if initiator_id == self.id:
            if completed_reports is not None:
                self.display_completed_snapshot(snapshot_id, completed_reports)
            return

        initiator = find_node_config(initiator_id, self.nodes)
        if initiator is None:
            print_message(
                f"[SNAPSHOT {snapshot_id}] Iniciador {initiator_id} não encontrado."
            )
            return

        with self.vector_clock_lock:
            vector_clock = self.vector_clock.copy()
        dto = NodeDto(
            type=MessageType.SNAPSHOT_REPORT.value,
            origin=self.id,
            destination=initiator_id,
            timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            vector_clock=vector_clock,
            snapshot_id=snapshot_id,
            snapshot_state=report,
        )
        self.send_to_node(initiator, dto)

    def handle_snapshot_report(self, payload: NodeDto) -> None:
        if payload.snapshot_id is None or payload.snapshot_state is None:
            raise ValueError("Relatório de snapshot incompleto")

        completed_reports: dict[int, dict[str, object]] | None = None
        with self.snapshot_lock:
            session = self.snapshots.get(payload.snapshot_id)
            if session is None or session.initiator_id != self.id:
                return
            if payload.origin not in session.members:
                return

            session.reports[payload.origin] = payload.snapshot_state
            completed_reports = self.complete_snapshot_if_ready(session)

        if completed_reports is not None:
            self.display_completed_snapshot(payload.snapshot_id, completed_reports)

    def complete_snapshot_if_ready(
        self, session: SnapshotSession
    ) -> dict[int, dict[str, object]] | None:
        if session.completed or not session.reported:
            return None
        if not session.members.issubset(session.reports):
            return None

        session.completed = True
        return session.reports.copy()

    def display_completed_snapshot(
        self,
        snapshot_id: str,
        reports: dict[int, dict[str, object]],
    ) -> None:
        self.completed_snapshots[snapshot_id] = reports
        print_message(format_snapshot(snapshot_id, reports))

    def handle_message(self, data: bytes) -> None:
        if not data:
            return

        try:
            payload = NodeDto(**json.loads(data.decode("utf-8")))
            self.receive_channel_message(payload)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            print_message("Erro ao decodificar mensagem.")

    def receive_channel_message(self, payload: NodeDto) -> None:
        sequence = payload.channel_sequence
        if sequence is None:
            self.dispatch_message(payload)
            return
        if sequence < 1:
            raise ValueError("Sequência de canal inválida")

        channel_origin = payload.channel_origin or payload.origin
        ready: list[NodeDto] = []
        with self.incoming_channel_lock:
            expected = self.incoming_next_sequence.setdefault(channel_origin, 1)
            if sequence < expected:
                return

            buffer = self.incoming_channel_buffers.setdefault(channel_origin, {})
            buffer.setdefault(sequence, payload)

            while expected in buffer:
                ready.append(buffer.pop(expected))
                expected += 1
            self.incoming_next_sequence[channel_origin] = expected

        for ordered_payload in ready:
            self.dispatch_message(ordered_payload)

    def dispatch_message(self, payload: NodeDto) -> None:
        with self.event_lock:
            if payload.type != MessageType.SNAPSHOT_MARKER.value:
                self.record_snapshot_message(payload)

            if payload.type == MessageType.SNAPSHOT_MARKER.value:
                self.handle_snapshot_marker(payload)

            elif payload.type == MessageType.SNAPSHOT_REPORT.value:
                self.handle_snapshot_report(payload)

            elif payload.type == MessageType.ORDER_STATE_REQUEST.value:
                self.handle_order_state_request(payload)

            elif payload.type == MessageType.ORDER_STATE_RESPONSE.value:
                self.handle_order_state_response(payload)

            if payload.type == MessageType.GROUP_MESSAGE_REQUEST.value:
                if self.id != self.leader_id:
                    print_message("Requisição de ordem recebida por um não líder.")
                    return
                self.handle_vector_clock(payload.vector_clock)
                self.sequence_group_message(payload)

            elif payload.type == MessageType.ORDERED_GROUP_MESSAGE.value:
                self.receive_ordered_message(payload)

            elif payload.type == MessageType.PRIVATE_MESSAGE.value:
                self.handle_vector_clock(payload.vector_clock)
                print_message(f"[PRIVADA] {format_message(payload)}")

            elif payload.type == MessageType.ELECTION.value:
                print_message(
                    f"[ELEIÇÃO] Solicitação recebida do Node {payload.origin}."
                )

                if self.id > payload.origin:
                    self.start_election()

            elif payload.type == MessageType.COORDINATOR.value:
                self.update_node_status(self.leader_id)
                self.leader_id = payload.origin
                with self.election_lock:
                    self.election_in_progress = False
                print_message(f"[COORDENADOR] Node {payload.origin} é o novo líder.")
                self.retry_pending_group_requests()

            elif payload.type == MessageType.HEARTBEAT.value:
                self.handle_heartbeat(payload.origin)

            elif payload.type == MessageType.HEARTBEAT_ACK.value:
                if self.id == self.leader_id:
                    with self.heartbeat_lock:
                        control = self.last_seen_control[payload.origin]
                        control.missed_acks = 0
                        control.timestamp = time.monotonic()

            elif payload.type == MessageType.UPDATE_LIST.value:
                inactivated_node = int(payload.message)
                self.update_node_status(inactivated_node)
                print_message(f"[ATUALIZAÇÃO] Node {inactivated_node} foi inativado")

    def handle_vector_clock(self, payload_vector_clock: list[int]) -> None:
        if len(payload_vector_clock) != len(self.vector_clock):
            raise ValueError("Relógio vetorial com tamanho incompatível")

        with self.vector_clock_lock:
            for i, received_value in enumerate(payload_vector_clock):
                self.vector_clock[i] = max(self.vector_clock[i], received_value)

            self.vector_clock[self.id - 1] += 1

    def heartbeat(self) -> None:
        time.sleep(2)
        while True:
            if self.id == self.leader_id:
                for node in self.nodes:
                    if node.id == self.leader_id or not node.is_active:
                        continue

                    with self.vector_clock_lock:
                        vector_clock = self.vector_clock.copy()
                    dto = NodeDto(
                        origin=self.id,
                        destination=node.id,
                        type=MessageType.HEARTBEAT.value,
                        timestamp=datetime.now(timezone.utc)
                        .astimezone()
                        .strftime("%H:%M:%S"),
                        vector_clock=vector_clock,
                    )
                    self.send_to_node(node, dto)

            time.sleep(HEARTBEAT_INTERVAL)

    def handle_heartbeat(self, leader_id: int) -> None:
        if self.id == self.leader_id:
            return

        if leader_id != self.leader_id:
            return

        with self.heartbeat_lock:
            control = self.last_seen_control.get(leader_id)
            if control is not None:
                control.timestamp = time.monotonic()
                control.missed_acks = 0

        with self.vector_clock_lock:
            vector_clock = self.vector_clock.copy()
        dto = NodeDto(
            origin=self.id,
            destination=self.leader_id,
            type=MessageType.HEARTBEAT_ACK.value,
            timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            vector_clock=vector_clock,
        )

        leader = find_node_config(leader_id, self.nodes)
        if leader is not None:
            self.send_to_node(leader, dto)

    def health_check(self) -> None:
        while True:
            if self.id == self.leader_id:
                now_ = time.monotonic()

                with self.heartbeat_lock:
                    for node in self.nodes:
                        if node.id == self.id or not node.is_active:
                            continue

                        last_ack = self.last_seen_control[node.id].timestamp
                        if (now_ - last_ack) > HEARTBEAT_TIMEOUT:
                            self.last_seen_control[node.id].missed_acks += 1

                            if (
                                self.last_seen_control[node.id].missed_acks
                                >= MAX_MISSED_ACKS
                            ):
                                node.is_active = False
                                self.broadcast_node_status_update(node.id)

            else:
                with self.heartbeat_lock:
                    leader_control = self.last_seen_control.get(self.leader_id)
                    leader_timed_out = (
                        leader_control is not None
                        and time.monotonic() - leader_control.timestamp
                        > HEARTBEAT_TIMEOUT
                    )

                    if leader_timed_out:
                        leader_control.missed_acks += 1
                        should_elect = leader_control.missed_acks >= MAX_MISSED_ACKS
                    else:
                        should_elect = False

                if should_elect:
                    print_message("Líder indisponível; iniciando eleição.")
                    self.update_node_status(self.leader_id)
                    self.start_election()

            time.sleep(HEARTBEAT_INTERVAL)

    def broadcast_node_status_update(self, inactivated_node: int) -> None:
        for node in self.nodes:
            with self.vector_clock_lock:
                vector_clock = self.vector_clock.copy()
            dto = NodeDto(
                message=inactivated_node,
                origin=self.id,
                destination=node.id,
                type=MessageType.UPDATE_LIST.value,
                timestamp=datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
                vector_clock=vector_clock,
            )

            destination_node = find_node_config(node.id, self.nodes)
            self.send_to_node(destination_node, dto)
