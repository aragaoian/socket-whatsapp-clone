import argparse
import atexit
import subprocess
import time

processes: list[subprocess.Popen] = []

def kill_child_process():
    for process in processes:
        if process.poll() is None:  # Check if the process is still running
            print(f"\nMain program exiting. Killing child process {process.pid}...")
            process.kill()     # Sends a SIGTERM signal (or calls TerminateProcess on Windows)
            process.wait()          # Clean up system resources

atexit.register(kill_child_process)


def lauch():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=False, default=3)
    args = parser.parse_args()

    

    for id in range(1, args.count + 1):
        processes.append(
            subprocess.Popen(
                ["uv", "run", "lauch_node.py", "--id", str(id)]
            )
        )
    

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user!")



if __name__ == "__main__":
    lauch()
