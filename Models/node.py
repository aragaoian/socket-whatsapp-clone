class Node:
    def __init__(self):
        self.id = None
        self.host = None
        self.port = None
        self.nodes = None
        self.leader_id = None
        self.lamport_clock = None
        self.vector_clock = None
        self.delivery_node = None
        self.global_delivery = None
        self.tcp_server = None

    def initialize_node(id: int) -> None:
        raise NotImplementedError
