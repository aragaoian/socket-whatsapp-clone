from dataclasses import dataclass


@dataclass
class NodeConfig:
    id: int
    port: int
    host: str
