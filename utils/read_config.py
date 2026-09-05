import json

from models.node_config import NodeConfig


def read_config_file(file_path: str, active_nodes_count: int) -> list[NodeConfig]:
    active_nodes_list = []
    with open(file_path, "r") as f:
        data = json.load(f)
        if data.get("nodes"):
            for i, node in enumerate(data["nodes"]):
                if i + 1 > active_nodes_count:
                    break
                active_nodes_list.append(
                    NodeConfig(
                        id=int(node["id"]),
                        port=int(node["port"]),
                        host=str(node["host"]),
                    )
                )
    return active_nodes_list
