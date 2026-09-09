import json
import unittest
from unittest.mock import patch

from models.node_config import NodeConfig
from services.node import Node


class PrivateMessageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes: dict[int, Node] = {}
        for own_id in (1, 2):
            configs = [
                NodeConfig(
                    id=node_id,
                    host="127.0.0.1",
                    port=19200 + node_id,
                    is_active=True,
                )
                for node_id in (1, 2)
            ]
            self.nodes[own_id] = Node(
                own_id,
                "127.0.0.1",
                19200 + own_id,
                configs,
                1,
                [0, 0],
            )

        self.nodes_by_port = {node.port: node for node in self.nodes.values()}
        self.print_patch = patch("services.node.print_message")
        self.send_patch = patch(
            "services.node.Socket.send",
            side_effect=self.route_message,
        )
        self.print_message = self.print_patch.start()
        self.send_patch.start()

    def tearDown(self) -> None:
        self.send_patch.stop()
        self.print_patch.stop()

    def route_message(self, _host: str, port: int, payload: dict) -> None:
        self.nodes_by_port[port].handle_message(
            json.dumps(payload).encode("utf-8")
        )

    def printed_messages(self) -> list[str]:
        return [call.args[0] for call in self.print_message.call_args_list]

    def test_private_message_reaches_only_the_destination(self) -> None:
        self.nodes[1].handle_command("send 2 mensagem reservada")

        private_logs = [
            message
            for message in self.printed_messages()
            if message.startswith("[PRIVADA]")
        ]
        self.assertEqual(len(private_logs), 1)
        self.assertIn("Node 1", private_logs[0])
        self.assertIn("mensagem reservada", private_logs[0])
        self.assertEqual(self.nodes[2].vector_clock, [1, 1])
        self.assertEqual(self.nodes[2].local_history, [])
        self.assertEqual(self.nodes[2].global_history, [])
        self.assertEqual(self.nodes[1].local_history[0].destination, 2)

    def test_group_message_is_not_labeled_private_or_counted_twice(self) -> None:
        self.nodes[1].handle_command("sendall mensagem do grupo")

        self.assertFalse(
            any(
                message.startswith("[PRIVADA]")
                for message in self.printed_messages()
            )
        )
        self.assertEqual(self.nodes[2].vector_clock, [1, 1])
        self.assertEqual(
            [message.global_sequence for message in self.nodes[2].global_history],
            [1],
        )


if __name__ == "__main__":
    unittest.main()
