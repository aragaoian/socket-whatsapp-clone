import json
import shutil
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime
from threading import Lock, Thread

from enums.commands import Commands
from models.node_config import NodeConfig
from models.node_dto import NodeDto
from services.socket import Socket
from services.terminal import RESET_SCROLL, print_message, setup_terminal
from utils.find_node import find_node_config
from utils.formatting import format_message


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
                comando = input("1> ")

                if not self.handle_command(comando):
                    break

            except (KeyboardInterrupt, EOFError):
                sys.stdout.write(RESET_SCROLL)
                break

    def handle_command(self, command_str: str) -> bool:
        command = command_str.split(" ")[0].lower()
        now_ = datetime.now().strftime("%H:%M:%S")

        if command == Commands.SEND.value:
            destination_node_id = int(command_str.split()[1])
            message = " ".join(command_str.split()[2:])
            node_info = find_node_config(destination_node_id, self.nodes)

            self.vector_clock[self.id - 1] += 1

            dto = NodeDto(
                type="MESSAGE",
                origin=self.id,
                timestamp=now_,
                vector_clock=self.vector_clock,
                message=message,
            )
            Socket.send(node_info.host, node_info.port, asdict(dto))
            return True

        if command == Commands.SEND_ALL.value:
            message = " ".join(command_str.split()[1:])
            for node_info in self.nodes:
                if node_info.id == self.id:
                    continue

                self.vector_clock[self.id - 1] += 1

                dto = NodeDto(
                    type="MESSAGE",
                    origin=self.id,
                    timestamp=now_,
                    vector_clock=self.vector_clock,
                    message=message,
                )
                Socket.send(node_info.host, node_info.port, asdict(dto))
                time.sleep(1)
            return True

        if command == Commands.EXIT.value:
            sys.stdout.write(RESET_SCROLL)
            print("\nPrograma encerrado.")
            return False

        return True

    def handle_message(self, data: bytes) -> None:
        if not data:
            return

        try:
            payload = NodeDto(**json.loads(data.decode("utf-8")))
            self.handle_vector_clock(payload.vector_clock)
            message = format_message(payload)
            print_message(message)
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = "Erro ao decodificar mensagem."

    def handle_vector_clock(self, payload_vector_clock: list[int]) -> None:
        # NOTE
        # Não precisa criar o delivery buffer porque vamos usar o
        # algoritmo do bully para ordenação.

        # TODO
        # tem algo relacionado a esse lock que ta crashando o node
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
                dto = NodeDto(message="ACK", origin=self.id, type="HEARTBEAT")
                Socket.send(node.host, node.port, asdict(dto))
                time.sleep(5)
