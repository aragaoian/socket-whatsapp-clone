import json
import unittest
from unittest.mock import patch

from enums.message_types import MessageType
from models.node_config import NodeConfig
from models.node_dto import NodeDto
from services.node import Node


class SnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes: dict[int, Node] = {}
        for own_id in (1, 2):
            configs = [
                NodeConfig(
                    id=node_id,
                    host="127.0.0.1",
                    port=19000 + node_id,
                    is_active=True,
                )
                for node_id in (1, 2)
            ]
            self.nodes[own_id] = Node(
                own_id,
                "127.0.0.1",
                19000 + own_id,
                configs,
                1,
                [0, 0],
            )

        self.nodes_by_port = {node.port: node for node in self.nodes.values()}
        self.wire: list[tuple[int, dict]] = []
        self.print_patch = patch("services.node.print_message")
        self.send_patch = patch(
            "services.node.Socket.send",
            side_effect=self.queue_message,
        )
        self.print_patch.start()
        self.send_patch.start()

    def tearDown(self) -> None:
        self.send_patch.stop()
        self.print_patch.stop()

    def queue_message(self, _host: str, port: int, payload: dict) -> None:
        self.wire.append((port, payload))

    def deliver(self, origin: int, destination: int, message_type: str) -> None:
        destination_port = self.nodes[destination].port
        for index, (port, payload) in enumerate(self.wire):
            if (
                payload["origin"] == origin
                and port == destination_port
                and payload["type"] == message_type
            ):
                self.wire.pop(index)
                self.nodes_by_port[port].handle_message(
                    json.dumps(payload).encode("utf-8")
                )
                return
        self.fail(
            f"Mensagem {message_type} de {origin} para {destination} não encontrada"
        )

    def test_snapshot_records_a_message_in_transit(self) -> None:
        snapshot_id = self.nodes[1].initiate_snapshot()

        self.nodes[2].handle_command("send 1 mensagem-em-transito")

        self.deliver(2, 1, MessageType.PRIVATE_MESSAGE.value)
        self.deliver(1, 2, MessageType.SNAPSHOT_MARKER.value)
        self.deliver(2, 1, MessageType.SNAPSHOT_MARKER.value)
        self.deliver(2, 1, MessageType.SNAPSHOT_REPORT.value)

        reports = self.nodes[1].completed_snapshots[snapshot_id]
        channel_state = reports[1]["channel_states"]["2"]

        self.assertEqual(set(reports), {1, 2})
        self.assertEqual(len(reports[1]["local_state"]["local_history"]), 0)
        self.assertEqual(len(reports[2]["local_state"]["local_history"]), 1)
        self.assertEqual(len(channel_state), 1)
        self.assertEqual(channel_state[0]["type"], MessageType.PRIVATE_MESSAGE.value)
        self.assertEqual(channel_state[0]["message"], "mensagem-em-transito")

    def test_logical_channel_delivers_connections_in_fifo_order(self) -> None:
        receiver = self.nodes[2]
        second = NodeDto(
            type=MessageType.ORDERED_GROUP_MESSAGE.value,
            origin=1,
            timestamp="10:00:01",
            vector_clock=[2, 0],
            message="segunda",
            local_sequence=2,
            global_sequence=2,
            channel_origin=1,
            channel_sequence=2,
        )
        first = NodeDto(
            type=MessageType.ORDERED_GROUP_MESSAGE.value,
            origin=1,
            timestamp="10:00:00",
            vector_clock=[1, 0],
            message="primeira",
            local_sequence=1,
            global_sequence=1,
            channel_origin=1,
            channel_sequence=1,
        )

        receiver.receive_channel_message(second)
        self.assertEqual(receiver.global_history, [])
        self.assertEqual(sorted(receiver.incoming_channel_buffers[1]), [2])

        receiver.receive_channel_message(first)
        self.assertEqual(
            [message.global_sequence for message in receiver.global_history],
            [1, 2],
        )
        self.assertEqual(receiver.incoming_channel_buffers[1], {})

    def test_single_node_snapshot_completes_immediately(self) -> None:
        only_node = Node(
            1,
            "127.0.0.1",
            19101,
            [NodeConfig(1, 19101, "127.0.0.1", True)],
            1,
            [0],
        )

        snapshot_id = only_node.initiate_snapshot()

        self.assertEqual(set(only_node.completed_snapshots[snapshot_id]), {1})


if __name__ == "__main__":
    unittest.main()
