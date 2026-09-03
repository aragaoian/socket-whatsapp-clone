import argparse

from consts.config import CONFIG_FILE_PATH
from services.node import Node
from utils.find_node import find_node_config
from utils.read_config import read_config_file

parser = argparse.ArgumentParser()
parser.add_argument("--id", type=int, required=True)
args = parser.parse_args()

nodes = read_config_file(CONFIG_FILE_PATH)
node_config = find_node_config(args.id, nodes)

node = Node(
    id=node_config["id"],
    host=node_config["host"],
    port=node_config["port"],
    nodes=nodes,
    leader_id=1,
    lamport_clock=0,
    vector_clock=[0, 0, 0],
)

node.start()
