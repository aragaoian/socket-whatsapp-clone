import json
import unittest
from unittest.mock import patch

from enums.message_types import MessageType
from models.node_config import NodeConfig
from models.node_dto import NodeDto
from services.node import Node


class OrderRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes: dict[int, Node] = {}
        for own_id in (1, 2, 3):
            configs = [
                NodeConfig(
                    id=node_id,
                    host="127.0.0.1",
                    port=19300 + node_id,
                    is_active=True,
                )
                for node_id in (1, 2, 3)
            ]
            self.nodes[own_id] = Node(
                own_id,
                "127.0.0.1",
                19300 + own_id,
                configs,
                1,
                [0, 0, 0],
            )

        self.nodes_by_port = {node.port: node for node in self.nodes.values()}
        self.print_patch = patch("services.node.print_message")
        self.send_patch = patch(
            "services.node.Socket.send",
            side_effect=self.route_message,
        )
        self.print_patch.start()
        self.send_patch.start()

    def tearDown(self) -> None:
        self.send_patch.stop()
        self.print_patch.stop()

    def route_message(self, _host: str, port: int, payload: dict) -> None:
        if port == self.nodes[1].port:
            raise ConnectionRefusedError("líder anterior indisponível")
        self.nodes_by_port[port].handle_message(json.dumps(payload).encode("utf-8"))

    @staticmethod
    def ordered_message(sequence: int, origin: int) -> NodeDto:
        vector_clock = [0, 0, 0]
        vector_clock[origin - 1] = sequence
        return NodeDto(
            type=MessageType.ORDERED_GROUP_MESSAGE.value,
            origin=origin,
            timestamp=f"10:00:0{sequence}",
            vector_clock=vector_clock,
            message=f"mensagem-{sequence}",
            local_sequence=sequence,
            global_sequence=sequence,
        )

    def test_new_leader_recovers_missing_message_before_sequencing(self) -> None:
        first = self.ordered_message(1, 1)
        second = self.ordered_message(2, 2)

        self.nodes[2].receive_ordered_message(first)
        self.nodes[2].receive_ordered_message(second)
        self.nodes[3].receive_ordered_message(first)

        new_leader = self.nodes[3]
        new_leader.leader_id = 3
        new_leader.leader_ready = False

        self.assertTrue(new_leader.recover_global_order())
        new_leader.leader_ready = True

        self.assertEqual(
            [message.global_sequence for message in new_leader.global_history],
            [1, 2],
        )
        self.assertEqual(new_leader.next_global_sequence, 3)

        request = NodeDto(
            type=MessageType.GROUP_MESSAGE_REQUEST.value,
            origin=2,
            timestamp="10:00:03",
            vector_clock=[1, 2, 0],
            message="mensagem-3",
            local_sequence=3,
        )
        new_leader.sequence_group_message(request)

        for node_id in (2, 3):
            self.assertEqual(
                [
                    message.global_sequence
                    for message in self.nodes[node_id].global_history
                ],
                [1, 2, 3],
            )
        self.assertFalse(new_leader.nodes[0].is_active)


if __name__ == "__main__":
    unittest.main()
