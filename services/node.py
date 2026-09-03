import json
import signal
import tkinter as tk
from queue import Queue
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
        self.root = None
        self.ui_queue = Queue()

    def close(self) -> None:
        if self.root is not None:
            try:
                self.root.destroy()
            finally:
                self.root = None

        if self.tcp_server is not None:
            try:
                self.tcp_server.shutdown(2)
            except OSError:
                pass
            finally:
                self.tcp_server.close()
                self.tcp_server = None

    def start(self) -> None:
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
            Thread(target=self.ui, daemon=True),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # TODO
        # 1. thread heartbeat []
        # 2. thread message processing []
        # 3. thread ui [X]

    def process_ui_queue(self, text_box: tk.Text):
        while not self.ui_queue.empty():
            message = self.ui_queue.get()
            text_box.insert(message)

        self.root.after(100, self.process_ui_queue)

    def ui(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title(f"Distributed Chat - Node {self.id}")
        root.protocol("WM_DELETE_WINDOW", self.close)

        label = tk.Label(root, text=f"Node {self.id}")
        label.pack()

        entry = tk.Entry(root)
        entry.pack()

        send_button = tk.Button(root, text="Send")
        send_button.pack()

        text_box = tk.Text(root, height=5, width=45, wrap="word")
        text_box.pack(pady=20)

        self.process_ui_queue(text_box)

        root.mainloop()
        self.root = None

    def handle_message(self, data: bytes) -> None:
        if not data:
            return

        try:
            payload = str(json.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = "Erro ao decodificar mensagem."

        self.ui_queue.put(payload)

    def heartbeat(self) -> None:
        raise NotImplementedError
