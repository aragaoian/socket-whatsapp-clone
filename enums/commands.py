from enum import Enum


class Commands(Enum):
    SEND = "send"
    SEND_ALL = "sendall"
    LOCAL = "local"
    GLOBAL = "global"
    STATUS = "status"
    LIST = "list"
    SNAPSHOT = "snapshot"
    HELP = "help"
    EXIT = "exit"
