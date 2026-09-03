from dataclasses import dataclass


@dataclass
class NodeDto:
    type: str  # "GROUP" or "SINGLE"
    origin: int
    message: str
