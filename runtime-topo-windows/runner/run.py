from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import yaml

from runner.opencode import SshTarget, encoded_powershell
from runner.real_canary import run as run_real_canary
from runner.report import JsonlLog, utc_now, write_json_atomic


ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def make_target(config: dict) -> SshTarget:
    guest = config["guest"]
    return SshTarget(
        address=guest["address"], user=guest["user"],
        identity=Path(guest["ssh_key"]), known_hosts=Path(guest["known_hosts"]),
    )


def transport_canary(config: dict, output: Path) -> int:
    run_id = "transport-" + utc_now().replace(":", "").replace("-", "") + "-" + uuid.uuid4().hex[:8]
    run_dir = output / run_id
    orchestrator = JsonlLog(run_dir / "orchestrator.jsonl", "orchestrator")
    agent = JsonlLog(run_dir / "agent.jsonl", "agent")
    evaluator = JsonlLog(run_dir / "evaluator.jsonl", "evaluator")
    target = make_target(config)
    sentinel = "WCB_TRANSPORT_CANARY_v1\r\n"
    path = r"C:\WCB\canary\transport.txt"
    script = (
        "$ErrorActionPreference='Stop';"
        "New-Item -ItemType Directory -Force -Path C:\\WCB\\canary|Out-Null;"
        f"[IO.File]::WriteAllBytes('{path}',[Text.Encoding]::UTF8.GetBytes(\"WCB_TRANSPORT_CANARY_v1`r`n\"));"
        f"$b=[IO.File]::ReadAllBytes('{path}');"
        "[Convert]::ToBase64String($b)"
    )
    orchestrator.emit("run_started", run_id=run_id, mode="transport-canary", guest=config["guest"]["address"])
    result = target.run(encoded_powershell(script), timeout=config["runtime"]["ssh_timeout_seconds"])
    agent.emit("ssh_exec", exit_code=result.returncode, stdout=result.stdout.decode("utf-8", "replace"), stderr=result.stderr.decode("utf-8", "replace"))
    expected_b64 = "V0NCX1RSQU5TUE9SVF9DQU5BUllfdjENCg=="
    actual = result.stdout.decode("utf-8", "replace").strip()
    passed = result.returncode == 0 and actual == expected_b64
    evaluator.emit("exact_bytes", passed=passed, expected_base64=expected_b64, actual_base64=actual)
    metadata = {"schema": "wcb.run-metadata/v1", "run_id": run_id, "started_at": utc_now(), "mode": "transport-canary", "passed": passed}
    write_json_atomic(run_dir / "metadata.json", metadata)
    write_json_atomic(run_dir / "score.json", {"passed": passed, "score": 1 if passed else 0})
    orchestrator.emit("run_finished", passed=passed)
    print(json.dumps({"run_id": run_id, "run_dir": str(run_dir), "passed": passed}))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("transport-canary", "opencode-canary"))
    parser.add_argument("--config", type=Path, default=ROOT / "benchmark.yaml")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    output = args.output or Path(config["storage"]["runs"])
    if args.command == "transport-canary":
        return transport_canary(config, output)
    if args.command == "opencode-canary":
        return run_real_canary(config, ROOT, output)
    return 2


if __name__ == "__main__":
    sys.exit(main())
