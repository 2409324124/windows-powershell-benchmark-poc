from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def run_libvirt(arguments: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    command = " ".join(subprocess.list2cmdline([item]) for item in ["virsh", "--connect", "qemu:///system", *arguments])
    return subprocess.run(["sg", "libvirt", "-c", command], text=True, capture_output=True, timeout=timeout, check=False)


def sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()

