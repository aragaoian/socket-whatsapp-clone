from models.node_config import NodeConfig
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


def format_node_list(nodes: list[NodeConfig]) -> str:
    headers = ("Nó", "Host", "Porta", "Status")
    rows = [
        (
            str(node.id),
            node.host,
            str(node.port),
            "Ativo" if node.is_active else "Inativo",
        )
        for node in sorted(nodes, key=lambda node: node.id)
    ]
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    def separator() -> str:
        return "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def row(values: tuple[str, ...]) -> str:
        return (
            "| "
            + " | ".join(
                value.ljust(widths[index]) for index, value in enumerate(values)
            )
            + " |"
        )

    lines = [separator(), row(headers), separator()]
    lines.extend(row(values) for values in rows)
    lines.append(separator())
    return "\n".join(lines)
