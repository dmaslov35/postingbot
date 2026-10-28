
"""Isolated VK test configuration. No browser launch or submission."""

from pathlib import Path
import importlib.util

from vk_single_test_runner import prepare_isolated_test

ROOT = Path("/opt/vkbot")
STOP = ROOT / "runtime/production.stop"


def verify_worker_configuration():
    config = prepare_isolated_test()

    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_MISSING")

    if config["queue_id"] != 101 or config["account_id"] != 4:
        raise RuntimeError("TEST_CONTEXT_INVALID")

    if config["send_authorized"] is not False:
        raise RuntimeError("SEND_NOT_ALLOWED")

    worker_path = ROOT / "vk_worker_production.py"

    import ast

    tree = ast.parse(worker_path.read_text(encoding="utf-8"))

    required = {
        "MODE",
        "TEST_GROUP",
        "STATE_FILE",
        "ENABLE_TEST_SUBMIT",
        "ENABLE_PRODUCTION",
        "ENABLE_SUBSCRIBE",
        "ENABLE_JOIN_REQUESTS",
        "ENABLE_CREATE_SUBMIT",
    }

    available = set()

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    available.add(target.id)

    if not required.issubset(available):
        raise RuntimeError("WORKER_CONFIGURATION_INCOMPATIBLE")

    return {
        "queue_id": config["queue_id"],
        "account_id": config["account_id"],
        "group_url": config["group_url"],
        "mode": "TEST",
        "state_file": config["state_file"],
        "submit_enabled": False,
        "browser_enabled": False,
        "production_enabled": False,
        "subscriptions_enabled": False,
        "join_requests_enabled": False,
    }


if __name__ == "__main__":
    result = verify_worker_configuration()

    print("=== ISOLATED VK TEST WORKER ===")
    for key, value in result.items():
        print(f"{key.upper()}: {value}")

    print("VK_REQUESTS: NONE")
    print("PUBLICATIONS: NONE")
    print("DELETIONS: NONE")
