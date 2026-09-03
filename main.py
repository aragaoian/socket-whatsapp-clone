import os
import signal
import argparse
import subprocess


def lauch():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=False, default=3)
    args = parser.parse_args()

    processes: list[subprocess.Popen] = []

    for id in range(1, args.count + 1):
        processes.append(
            subprocess.Popen(
                ["uv", "run", "python", "-m", "lauch_node", "--id", str(id)]
            )
        )

    try:
        for process in processes:
            process.wait()
    except Exception:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)


if __name__ == "__main__":
    lauch()
