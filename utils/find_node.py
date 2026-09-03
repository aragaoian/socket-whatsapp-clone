def find_node_config(node_id: int, nodes_config: list[dict]) -> dict | None:
    for node in nodes_config:
        if node["id"] == node_id:
            return node
    return None
