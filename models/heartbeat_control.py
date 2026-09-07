from dataclasses import dataclass


@dataclass
class HeartbeatControl:
    timestamp: float = 0.0
    missed_acks: int = 0
