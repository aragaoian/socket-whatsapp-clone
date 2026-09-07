import json
import shutil
import signal
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from threading import Lock, Thread

from enums.commands import Commands
from enums.message_types import MessageType
from models.node_config import NodeConfig
from models.node_dto import NodeDto
from services.socket import Socket
from services.terminal import RESET_SCROLL, print_message, setup_terminal
from utils.find_node import find_node_config
from utils.formatting import (
    format_global_message,
    format_local_message,
    format_message,
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
        self.local_sequence = 0
        self.next_global_sequence = 1
        self.next_delivery_sequence = 1
        self.local_history: list[NodeDto] = []
        self.global_history: list[NodeDto] = []
        self.delivery_buffer: dict[int, NodeDto] = {}
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

        # NOTE
        # Close all windows if program is terminated
        signal.signal(signal.SIGINT, terminate)
        signal.signal(signal.SIGTERM, terminate)

        threads = [
            Thread(
                target=Socket.listen,
                args=(self.tcp_server, self.handle_message),
                daemon=True,
            ),
            # Thread(
            #     target=self.heartbeat,
            #     daemon=True,
            # ),
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

        if command == Commands.HELP.value:
            print_message(
                "Comandos: send <id> <msg>, sendall <msg>, local, global, status, exit"
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
        try:
            Socket.send(node.host, node.port, asdict(payload))
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
            print_message(f"Líder não acessível, reelegendo líder.")
            self.bully_election()

    def bully_election(self) -> None:
        higher_nodes = sorted(
            (node for node in self.nodes if node.id > self.id),
            key=lambda node: node.id,
        )

        election_message = NodeDto(
            type=MessageType.ELECTION.value,
            origin=self.id,
            timestamp=datetime.now(timezone.utc)
            .astimezone()
            .strftime("%H:%M:%S"),
            vector_clock=self.vector_clock.copy(),
            message="ELECTION",
        )

        higher_node_answered = False

        for node in higher_nodes:
            if self.send_to_node(node, election_message):
                higher_node_answered = True
                print_message(
                    f"[ELEIÇÃO] Node {node.id} está ativo; "
                    "ele continuará a eleição."
                )

        if higher_node_answered:
            print_message(
                "[ELEIÇÃO] Aguardando anúncio do novo coordenador."
            )
            return
        
        self.leader_id = self.id
        print_message(f"[COORDENADOR] Node {self.id} é o novo líder.")

        coordinator_message = NodeDto(
            type=MessageType.COORDINATOR.value,
            origin=self.id,
            timestamp=datetime.now(timezone.utc)
            .astimezone()
            .strftime("%H:%M:%S"),
            vector_clock=self.vector_clock.copy(),
            message="COORDINATOR",
        )

        for node in self.nodes:
            if node.id != self.id:
                self.send_to_node(node, coordinator_message)
        pass

    def sequence_group_message(self, payload: NodeDto) -> None:
        if self.id != self.leader_id:
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

    def handle_message(self, data: bytes) -> None:
        if not data:
            return

        try:
            payload = NodeDto(**json.loads(data.decode("utf-8")))
            if payload.type == MessageType.GROUP_MESSAGE_REQUEST.value:
                if self.id != self.leader_id:
                    print_message("Requisição de ordem recebida por um não líder.")
                    return
                self.handle_vector_clock(payload.vector_clock)
                self.sequence_group_message(payload)
            elif payload.type == MessageType.ORDERED_GROUP_MESSAGE.value:
                self.receive_ordered_message(payload)
            
                self.handle_vector_clock(payload.vector_clock)
                print_message(f"[PRIVADA] {format_message(payload)}")
            elif payload.type == MessageType.ELECTION.value:
                print_message(
                    f"[ELEIÇÃO] Solicitação recebida do Node {payload.origin}."
                )

                if self.id > payload.origin:
                    Thread(target=self.bully_election, daemon=True).start()

            elif payload.type == MessageType.COORDINATOR.value:
                self.leader_id = payload.origin
                print_message(
                    f"[COORDENADOR] Node {payload.origin} é o novo líder."
                )

        except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            print_message("Erro ao decodificar mensagem.")

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
            for node in self.nodes:
                if node.id == self.id:
                    continue
                with self.vector_clock_lock:
                    vector_clock = self.vector_clock.copy()
                dto = NodeDto(
                    message="ACK",
                    origin=self.id,
                    type=MessageType.HEARTBEAT.value,
                    timestamp=datetime.now(timezone.utc)
                    .astimezone()
                    .strftime("%H:%M:%S"),
                    vector_clock=vector_clock,
                )
                self.send_to_node(node, dto)
                time.sleep(5)
