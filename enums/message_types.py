from enum import Enum


class MessageType(Enum):
    MESSAGE = "MESSAGE"
    HEARTBEAT = "HEARTBEAT"
    ELECTION = "ELECTION"
    COORDINATOR = "COORDINATOR"
