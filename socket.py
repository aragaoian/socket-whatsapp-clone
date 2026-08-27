import json
import socket

BUFFER_SIZE = 65536
READABLE_BUFFER = 1
DEFAULT_HOST = "0.0.0.0"


class Socket:
    def __init__(self):
        pass

    def server(port: int, process_message: callable) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, READABLE_BUFFER)
        s.bind((DEFAULT_HOST, port))
        s.listen()

        while True:
            conn, _ = s.accept()
            with conn:
                data = conn.recv(BUFFER_SIZE)
                if data:
                    process_message(data)

    def send(host: str, port: int, payload: dict) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(json.dumps(payload).encode("utf-8"))
