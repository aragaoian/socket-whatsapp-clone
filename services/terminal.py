import shutil
import sys

CLEAR_SCREEN = "\033[2J"
RESET_SCROLL = "\033[r"
SAVE_CURSOR = "\033[s"
RESTORE_CURSOR = "\033[u"


def setup_terminal():
    """Configura o terminal dividindo-o em uma zona de rolagem e uma linha de prompt fixa."""
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
