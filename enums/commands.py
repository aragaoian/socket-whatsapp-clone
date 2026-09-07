from enum import Enum


class Commands(Enum):
    SEND = "send"
    SEND_ALL = "sendall"
    LOCAL = "local"
    GLOBAL = "global"
    STATUS = "status"
    LIST = "list"
    HELP = "help"
    EXIT = "exit"
