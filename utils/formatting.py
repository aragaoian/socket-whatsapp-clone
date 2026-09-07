from models.node_dto import NodeDto


def format_message(payload: NodeDto) -> str:
    return f"{payload.timestamp} - Node {payload.origin} | VClock {payload.vector_clock}: {payload.message}"


def format_local_message(payload: NodeDto) -> str:
    destination = (
        "grupo" if payload.destination is None else f"Node {payload.destination}"
    )
    return (
        f"[LOCAL {payload.local_sequence}] para {destination} | "
        f"VClock {payload.vector_clock}: {payload.message}"
    )


def format_global_message(payload: NodeDto) -> str:
    return (
        f"[GLOBAL {payload.global_sequence}] Node {payload.origin} "
        f"(local {payload.local_sequence}) | VClock {payload.vector_clock}: "
        f"{payload.message}"
    )
