from models.node_config import NodeConfig


def find_node_config(
    node_id: int, nodes_config: list[NodeConfig]
) -> NodeConfig | None:
    for node in nodes_config:
        if node.id == node_id:
            return node
    return None
