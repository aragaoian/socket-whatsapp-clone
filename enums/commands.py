from enum import Enum


class Commands(Enum):
    SEND = "send"
    SEND_ALL = "sendall"
    LOCAL = "local"
    GLOBAL = "global"
    STATUS = "status"
    HELP = "help"
    EXIT = "exit"
