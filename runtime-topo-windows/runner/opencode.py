from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence


@dataclass(frozen=True)
class SshTarget:
    address: str
    user: str
    identity: Path
    known_hosts: Path

    def base(self) -> list[str]:
        return [
            "sg", "libvirt", "-c",
            " ".join([
                "ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=yes", "-o",
                f"UserKnownHostsFile={self.known_hosts}", "-i", str(self.identity),
                f"{self.user}@{self.address}",
            ]),
        ]

    def run(self, command: str, *, timeout: int, stdin: BinaryIO | None = None) -> subprocess.CompletedProcess[bytes]:
        invocation = self.base()
        invocation[-1] += " " + subprocess.list2cmdline([command])
        if stdin is None:
            return subprocess.run(invocation, input=b"", capture_output=True, timeout=timeout, check=False)
        return subprocess.run(invocation, stdin=stdin, capture_output=True, timeout=timeout, check=False)


def encoded_powershell(script: str, *, executable: str = "powershell.exe") -> str:
    import base64

    payload = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"{executable} -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {payload}"


def opencode_command(
    executable: str,
    workspace: str,
    model: str,
    variant: str,
    agent: str,
    prompt: str,
) -> str:
    args: Sequence[str] = (
        executable, "--pure", "run", "--auto", "--agent", agent,
        "--format", "json", "--dir", workspace, "--model", model,
        "--variant", variant, prompt,
    )
    return subprocess.list2cmdline(list(args))
