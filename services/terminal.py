import ctypes
import os
import shutil
import sys

CLEAR_SCREEN = "\033[2J"
RESET_SCROLL = "\033[r"
SAVE_CURSOR = "\033[s"
RESTORE_CURSOR = "\033[u"


def _enable_windows_virtual_terminal():
    """Habilita sequencias ANSI/VT no console do Windows 10/11."""
    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.windll.kernel32
        stdout_handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)
    except (AttributeError, OSError):
        # Windows Terminal normally already supports VT. If enabling it explicitly
        # fails, keep going and let the host terminal handle the escape sequences.
        pass


def setup_terminal():
    """Configura o terminal dividindo-o em uma zona de rolagem e uma linha de prompt fixa."""
    _enable_windows_virtual_terminal()
    linhas = shutil.get_terminal_size().lines

    sys.stdout.write(CLEAR_SCREEN)
    sys.stdout.write(f"\033[1;{linhas - 1}r")
    sys.stdout.write(f"\033[{linhas};1H")
    sys.stdout.flush()


def print_message(message: str):
    linhas = shutil.get_terminal_size().lines

    sys.stdout.write(SAVE_CURSOR)
    sys.stdout.write(f"\033[{linhas - 1};1H\n")
    sys.stdout.write(f"{message}\r")
    sys.stdout.write(RESTORE_CURSOR)
    sys.stdout.flush()
