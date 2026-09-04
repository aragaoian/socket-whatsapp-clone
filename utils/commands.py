import sys
from time import sleep
from dataclasses import asdict

from enums.commands import Commands
from services.socket import Socket
from models.node_dto import NodeDto
from utils.find_node import find_node_config

RESET_SCROLL = "\033[r"


def command_handler(id: int, nodes: list[dict], command_str: str) -> bool:
    command = command_str.split(" ")[0].lower()

    if command == Commands.SEND.value:
        destination_node_id = int(command_str.split()[1])
        message = " ".join(command_str.split()[2:])
        node_info = find_node_config(destination_node_id, nodes)

        dto = NodeDto(
            type="MESSAGE",
            message=message,
            origin=id,
        )
        Socket.send(
            node_info["host"],
            node_info["port"],
            asdict(dto),
        )
        return True
    elif command == Commands.SEND_ALL.value:
        message = " ".join(command_str.split()[1:])
        for node_info in nodes:
            if node_info["id"] == id:
                continue

            dto = NodeDto(
                type="MESSAGE",
                message=message,
                origin=id,
            )
            Socket.send(
                node_info["host"],
                node_info["port"],
                asdict(dto),
            )
            # TODO
            # fix crashing when sending to all
            # obs: possible fix turn Socket.listen into async function
            sleep(1)
        return True
    elif command == Commands.EXIT.value:
        # Restaura o comportamento padrão do terminal antes de fechar
        sys.stdout.write(RESET_SCROLL)
        print("\nPrograma encerrado.")
        return False

    return True
