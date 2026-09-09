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
    channel_origin: int | None = None
    channel_sequence: int | None = None
    snapshot_id: str | None = None
    snapshot_initiator: int | None = None
    snapshot_members: list[int] | None = None
    snapshot_state: dict[str, object] | None = None
    recovery_id: str | None = None
    order_state: dict[str, object] | None = None
