from dataclasses import dataclass, field


@dataclass
class SnapshotSession:
    snapshot_id: str
    initiator_id: int
    members: set[int]
    local_state: dict[str, object]
    recording_channels: set[int]
    channel_states: dict[int, list[dict[str, object]]]
    reports: dict[int, dict[str, object]] = field(default_factory=dict)
    reported: bool = False
    completed: bool = False
