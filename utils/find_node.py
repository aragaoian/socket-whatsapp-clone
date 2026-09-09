from models.node_config import NodeConfig


def find_node_config(node_id: int, nodes_config: list[NodeConfig]) -> NodeConfig | None:
    for node in nodes_config:
        if node.id == node_id:
            return node
    return None


def find_initial_leader_id(nodes_config: list[NodeConfig]) -> int:
    active_node_ids = [node.id for node in nodes_config if node.is_active]
    if not active_node_ids:
        raise ValueError("Não há nós ativos para assumir a coordenação inicial")
    return max(active_node_ids)
