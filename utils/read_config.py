import json


def read_config_file(file_path: str) -> list[dict]:
    with open(file_path, "r") as f:
        data = json.load(f)
        if data:
            return data.get("nodes") or []
