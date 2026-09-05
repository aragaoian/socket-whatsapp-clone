from dataclasses import dataclass


@dataclass
class NodeDto:
    type: str  # MESSAGE, HEARBEAT, ELECTION, COORDINATOR
    origin: int
    timestamp: str
    vector_clock: list[int]
    message: str
