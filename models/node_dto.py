from dataclasses import dataclass


@dataclass
class NodeDto:
    type: str
    origin: int
    timestamp: str
    vector_clock: list[int]
    message: str = ""
    destination: int | None = None
    local_sequence: int | None = None
    global_sequence: int | None = None
