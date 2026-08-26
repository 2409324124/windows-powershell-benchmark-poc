from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Sequence


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

    def run(
        self,
        command: str,
        *,
        timeout: int,
        stdin: BinaryIO | None = None,
        on_timeout: Callable[[subprocess.TimeoutExpired], None] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        invocation = self.base()
        invocation[-1] += " " + subprocess.list2cmdline([command])
        if on_timeout is None:
            if stdin is None:
                return subprocess.run(invocation, input=b"", capture_output=True, timeout=timeout, check=False)
            return subprocess.run(invocation, stdin=stdin, capture_output=True, timeout=timeout, check=False)

        process_stdin = subprocess.PIPE if stdin is None else stdin
        with subprocess.Popen(
            invocation, stdin=process_stdin,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as process:
            try:
                stdout, stderr = process.communicate(
                    input=b"" if stdin is None else None,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as error:
                try:
                    on_timeout(error)
                finally:
                    process.kill()
                    stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(
                    error.cmd, error.timeout, output=stdout, stderr=stderr,
                ) from None
        return subprocess.CompletedProcess(invocation, process.returncode, stdout, stderr)


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
