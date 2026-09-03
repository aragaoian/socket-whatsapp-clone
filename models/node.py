import json
from threading import Thread

from services.socket import Socket


class Node:
    def __init__(
        self,
        id: int,
        host: str,
        port: int,
        nodes: dict,
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

    def handle_message(self, data: bytes) -> None:
        if not data:
            return

        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = data

        print(f"Node {self.id} received: {payload}")

    def start(self) -> None:
        self.tcp_server = Socket.server(self.port)
        thread = Thread(
            target=Socket.listen,
            args=(self.tcp_server, self.handle_message),
            daemon=True,
        )
        thread.start()
        thread.join()

    def heartbeat(self) -> None:
        pass
