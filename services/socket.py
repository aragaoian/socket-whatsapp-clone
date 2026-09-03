import json
import socket

BUFFER_SIZE = 65536
READABLE_BUFFER = 1
DEFAULT_HOST = "0.0.0.0"


class Socket:
    def __init__(self):
        pass

    @staticmethod
    def server(port: int) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, READABLE_BUFFER)
        s.bind((DEFAULT_HOST, port))
        return s

    @staticmethod
    def listen(s: socket.socket, process_message: callable) -> None:
        s.listen()
        while True:
            try:
                conn, _ = s.accept()
            except OSError:
                break

            with conn:
                data = conn.recv(BUFFER_SIZE)
                if data:
                    process_message(data)

    @staticmethod
    def send(host: str, port: int, payload: dict) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(json.dumps(payload).encode("utf-8"))
