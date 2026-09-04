import json
import shutil
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime
from queue import Queue
from threading import Thread

from models.node_dto import NodeDto
from services.socket import Socket
from utils.commands import command_handler

# Códigos de controle ANSI
CLEAR_SCREEN = "\033[2J"
RESET_SCROLL = "\033[r"
SAVE_CURSOR = "\033[s"
RESTORE_CURSOR = "\033[u"


def setup_terminal():
    """Configura o terminal dividindo-o em uma zona de rolagem e uma linha de prompt fixa."""
    # Obtém o tamanho atual da tela (número de linhas)
    linhas = shutil.get_terminal_size().lines

    sys.stdout.write(CLEAR_SCREEN)
    # Define a margem de rolagem: da linha 1 até a penúltima linha (linhas - 1)
    sys.stdout.write(f"\033[1;{linhas - 1}r")
    # Move o cursor para a última linha onde o prompt ficará fixo
    sys.stdout.write(f"\033[{linhas};1H")
    sys.stdout.flush()


def print_message(mensagem):
    """Imprime uma mensagem na zona de rolagem superior de forma limpa."""
    linhas = shutil.get_terminal_size().lines

    sys.stdout.write(SAVE_CURSOR)  # Salva onde o usuário está digitando
    sys.stdout.write(
        f"\033[{linhas - 1};1H\n"
    )  # Vai para o final da zona de rolagem e empurra para cima
    sys.stdout.write(f"{mensagem}\r")  # Imprime o novo log
    sys.stdout.write(
        RESTORE_CURSOR
    )  # Devolve o cursor para o prompt exatamente onde estava
    sys.stdout.flush()


class Node:
    def __init__(
        self,
        id: int,
        host: str,
        port: int,
        nodes: list[dict],
        leader_id: int,
        lamport_clock: int,
        vector_clock: list,
        delivery_node: "Node | None" = None,
    ):
        self.id = id
        self.host = host
        self.port = port
        self.nodes = nodes
        self.leader_id = leader_id
        self.lamport_clock = lamport_clock
        self.vector_clock = vector_clock
        self.delivery_node = delivery_node
        self.global_delivery = None
        self.tcp_server = None
        self.messages = []
        self.session = None

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
            Thread(
                target=self.heartbeat,
                daemon=True,
            ),
        ]

        for thread in threads:
            thread.start()

        self.tui()

        # TODO
        # 1. thread heartbeat []
        # 2. thread message processing []

    def tui(self) -> None:
        linhas = shutil.get_terminal_size().lines
        print_message(f"PORTA {self.port}")
        while True:
            # Garante que o cursor do input comece sempre na última linha
            sys.stdout.write(
                f"\033[{linhas};1H\033[2K"
            )  # Vai para a última linha e limpa ela
            sys.stdout.flush()

            try:
                # O input do usuário fica isolado na última linha do terminal
                comando = input("1> ")

                if not command_handler(self.id, self.nodes, comando):
                    break

            except (KeyboardInterrupt, EOFError):
                sys.stdout.write(RESET_SCROLL)
                break

    def handle_message(self, data: bytes) -> None:
        if not data:
            return

        try:
            payload = NodeDto(**json.loads(data.decode("utf-8")))
            if payload.type == "MESSAGE":
                print_message(
                    f"{datetime.now()} - Node {payload.origin}: {payload.message}"
                )
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = "Erro ao decodificar mensagem."

    def heartbeat(self) -> None:
        if self.port == 5002:
            return
        time.sleep(2)
        while True:
            dto = NodeDto(message="ack", origin=self.id, type="HEARTBEAT")
            Socket.send("127.0.0.1", 5002, asdict(dto))
            time.sleep(5)
