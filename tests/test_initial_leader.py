import unittest

from models.node_config import NodeConfig
from utils.find_node import find_initial_leader_id


class InitialLeaderTest(unittest.TestCase):
    def test_selects_highest_active_id(self) -> None:
        nodes = [
            NodeConfig(id=1, host="127.0.0.1", port=5001, is_active=True),
            NodeConfig(id=8, host="127.0.0.1", port=5008, is_active=True),
            NodeConfig(id=15, host="127.0.0.1", port=5015, is_active=True),
        ]

        self.assertEqual(find_initial_leader_id(nodes), 15)

    def test_ignores_inactive_nodes(self) -> None:
        nodes = [
            NodeConfig(id=1, host="127.0.0.1", port=5001, is_active=True),
            NodeConfig(id=3, host="127.0.0.1", port=5003, is_active=False),
            NodeConfig(id=2, host="127.0.0.1", port=5002, is_active=True),
        ]

        self.assertEqual(find_initial_leader_id(nodes), 2)

    def test_rejects_catalog_without_active_nodes(self) -> None:
        nodes = [
            NodeConfig(id=1, host="127.0.0.1", port=5001, is_active=False),
        ]

        with self.assertRaisesRegex(ValueError, "Não há nós ativos"):
            find_initial_leader_id(nodes)


if __name__ == "__main__":
    unittest.main()
