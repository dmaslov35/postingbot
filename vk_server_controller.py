#!/opt/vkbot/venv/bin/python

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

BASE = Path("/opt/vkbot")

COMMAND_FILE = BASE / "vk_worker_command.json"
CLOUD_STATE_FILE = BASE / "vk_worker_server_state.json"
PANEL_STATE_FILE = BASE / "vk_worker_final_state.json"
CONTROLLER_LOG = BASE / "vk_server_controller.log"

WORKER_SERVICE = "vkbot-cloud-scan.service"

POLL_SECONDS = 3

ALLOWED_COMMANDS = {
    "SCAN_START",
    "SCAN_STOP",
}

# Hard safety locks.
PRODUCTION_ENABLED = False
TELEGRAM_PUBLISH_ENABLED = False
TELEGRAM_SUBSCRIBE_ENABLED = False
TELEGRAM_JOIN_ENABLED = False
CREATE_SUBMIT_ENABLED = False


def now():
    return datetime.now().isoformat(timespec="seconds")


def log(message):
    line = f"[{now()}] {message}"
    print(line, flush=True)

    with CONTROLLER_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def atomic_write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.replace(tmp, path)


def read_json(path, default=None):
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        log(f"JSON READ ERROR {path.name}: {exc!r}")
        return default


def service_is_running():
    result = subprocess.run(
        [
            "systemctl",
            "is-active",
            "--quiet",
            WORKER_SERVICE,
        ],
        check=False,
    )

    return result.returncode == 0


def get_main_pid():
    result = subprocess.run(
        [
            "systemctl",
            "show",
            WORKER_SERVICE,
            "--property=MainPID",
            "--value",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    value = result.stdout.strip()

    try:
        pid = int(value)
    except Exception:
        return None

    return pid if pid > 0 else None


def start_scan():
    if service_is_running():
        return "ALREADY_RUNNING"

    result = subprocess.run(
        [
            "systemctl",
            "start",
            WORKER_SERVICE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"systemctl exit={result.returncode}"
        )
        raise RuntimeError(error)

    time.sleep(1)

    if service_is_running():
        return "STARTED"

    return "START_REQUESTED_BUT_NOT_RUNNING"


def stop_scan():
    if not service_is_running():
        return "ALREADY_STOPPED"

    result = subprocess.run(
        [
            "systemctl",
            "stop",
            WORKER_SERVICE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"systemctl exit={result.returncode}"
        )
        raise RuntimeError(error)

    return "STOPPED"


def summarize_cloud_state():
    cloud = read_json(
        CLOUD_STATE_FILE,
        {"groups": {}, "runs": []},
    )

    groups = cloud.get("groups", {})
    runs = cloud.get("runs", [])

    if not isinstance(groups, dict):
        groups = {}

    if not isinstance(runs, list):
        runs = []

    create_count = 0
    suggest_count = 0
    subscribed_count = 0
    not_subscribed_count = 0
    unknown_subscription_count = 0
    scan_only_count = 0
    error_count = 0
    errors_preview = []

    panel_groups = []

    for url, info in groups.items():
        if not isinstance(info, dict):
            info = {}

        status = info.get("status")
        subscription = info.get("subscription")
        create = bool(info.get("create"))
        suggest = bool(info.get("suggest"))
        error = info.get("error")

        if create:
            create_count += 1

        if suggest:
            suggest_count += 1

        if subscription == "SUBSCRIBED":
            subscribed_count += 1
        elif subscription == "NOT_SUBSCRIBED":
            not_subscribed_count += 1
        else:
            unknown_subscription_count += 1

        if status == "SCAN_ONLY":
            scan_only_count += 1

        if error:
            error_count += 1

            if len(errors_preview) < 5:
                errors_preview.append(
                    {
                        "url": url,
                        "error": str(error),
                    }
                )

        panel_groups.append(
            {
                "url": url,
                **info,
            }
        )

    last_run = runs[-1] if runs else {}

    if not isinstance(last_run, dict):
        last_run = {}

    finished_at = last_run.get("finished_at")

    return {
        "groups": panel_groups,
        "groups_in_state": len(groups),
        "create_count": create_count,
        "suggest_count": suggest_count,
        "subscribed_count": subscribed_count,
        "not_subscribed_count": not_subscribed_count,
        "unknown_subscription_count":
            unknown_subscription_count,
        "scan_only_count": scan_only_count,
        "error_count": error_count,
        "errors_preview": errors_preview,
        "runs": runs,
        "last_scan_finished_at": finished_at,
        "last_scan_status":
            "COMPLETED" if finished_at else None,
        "last_scan_subscriptions":
            last_run.get("subscriptions", 0),
        "last_scan_join_requests":
            last_run.get("join_requests", 0),
        "post_attempts":
            last_run.get("posts", 0),
    }


last_command = None
last_command_at = None
last_command_result = None


def publish_panel_state():
    summary = summarize_cloud_state()

    running = service_is_running()
    pid = get_main_pid() if running else None

    panel = {
        "bridge_version": "SERVER-1.0",
        "controller_enabled": True,
        "source": "server",
        "updated_at": now(),

        "production_enabled":
            PRODUCTION_ENABLED,
        "telegram_publish_enabled":
            TELEGRAM_PUBLISH_ENABLED,
        "telegram_subscribe_enabled":
            TELEGRAM_SUBSCRIBE_ENABLED,
        "telegram_join_enabled":
            TELEGRAM_JOIN_ENABLED,
        "create_submit_enabled":
            CREATE_SUBMIT_ENABLED,

        "telegram_scan_start_enabled": True,
        "telegram_scan_stop_enabled": True,

        "worker_running": running,
        "worker_pid": pid,
        "worker_file":
            "vk_worker_server_locked.py",

        "groups_total": 100,
        "groups_in_state":
            summary["groups_in_state"],
        "groups_recognized": True,
        "groups_source_path":
            "server.groups",

        "groups": summary["groups"],

        "create_count":
            summary["create_count"],
        "suggest_count":
            summary["suggest_count"],
        "subscribed_count":
            summary["subscribed_count"],
        "not_subscribed_count":
            summary["not_subscribed_count"],
        "unknown_subscription_count":
            summary["unknown_subscription_count"],
        "scan_only_count":
            summary["scan_only_count"],
        "error_count":
            summary["error_count"],
        "errors_preview":
            summary["errors_preview"],

        "last_scan_finished_at":
            summary["last_scan_finished_at"],
        "last_scan_status":
            summary["last_scan_status"],
        "last_scan_subscriptions":
            summary["last_scan_subscriptions"],
        "last_scan_join_requests":
            summary["last_scan_join_requests"],
        "post_attempts":
            summary["post_attempts"],

        "last_command": last_command,
        "last_command_at": last_command_at,
        "last_command_result":
            last_command_result,

        "vk_actions_by_bridge": 0,

        "runs": summary["runs"],
    }

    atomic_write_json(
        PANEL_STATE_FILE,
        panel,
    )


def consume_command():
    global last_command
    global last_command_at
    global last_command_result

    if not COMMAND_FILE.exists():
        return

    command_data = read_json(COMMAND_FILE)

    # Consume atomically before executing.
    try:
        COMMAND_FILE.unlink()
    except FileNotFoundError:
        return

    if not isinstance(command_data, dict):
        log("COMMAND REJECTED: invalid JSON structure")
        return

    command = command_data.get("command")

    if command not in ALLOWED_COMMANDS:
        last_command = str(command)
        last_command_at = now()
        last_command_result = "REJECTED"

        log(
            f"COMMAND REJECTED: {command!r}"
        )
        return

    last_command = command
    last_command_at = now()

    log(f"COMMAND RECEIVED: {command}")

    try:
        if command == "SCAN_START":
            result = start_scan()

        elif command == "SCAN_STOP":
            result = stop_scan()

        else:
            result = "REJECTED"

        last_command_result = result
        log(
            f"COMMAND RESULT: "
            f"{command} -> {result}"
        )

    except Exception as exc:
        last_command_result = (
            f"ERROR: {type(exc).__name__}: {exc}"
        )

        log(
            f"COMMAND ERROR: "
            f"{command}: {exc!r}"
        )


def assert_safety():
    if PRODUCTION_ENABLED:
        raise RuntimeError(
            "PRODUCTION MUST REMAIN LOCKED"
        )

    if TELEGRAM_PUBLISH_ENABLED:
        raise RuntimeError(
            "TELEGRAM PUBLISH MUST REMAIN LOCKED"
        )

    if TELEGRAM_SUBSCRIBE_ENABLED:
        raise RuntimeError(
            "TELEGRAM SUBSCRIBE MUST REMAIN LOCKED"
        )

    if TELEGRAM_JOIN_ENABLED:
        raise RuntimeError(
            "TELEGRAM JOIN MUST REMAIN LOCKED"
        )

    if CREATE_SUBMIT_ENABLED:
        raise RuntimeError(
            "CREATE SUBMIT MUST REMAIN LOCKED"
        )


def main():
    assert_safety()

    log("=" * 60)
    log("VK SERVER CONTROLLER START")
    log(
        "ALLOWLIST="
        + ",".join(sorted(ALLOWED_COMMANDS))
    )
    log("PRODUCTION=LOCKED")
    log("=" * 60)

    while True:
        try:
            consume_command()
            publish_panel_state()

        except Exception as exc:
            log(
                f"CONTROLLER LOOP ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
