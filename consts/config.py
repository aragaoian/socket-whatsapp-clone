import pathlib

CONFIG_FILE_PATH = str(pathlib.Path.cwd()) + "/json/nodes.json"
HEARTBEAT_TIMEOUT = 10.0
MAX_MISSED_ACKS = 3
HEARTBEAT_INTERVAL = 5
