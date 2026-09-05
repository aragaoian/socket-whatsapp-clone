from models.node_dto import NodeDto


def format_message(payload: NodeDto) -> str:
    return f"{payload.timestamp} - Node {payload.origin} | VClock {payload.vector_clock}: {payload.message}"
