from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from runner.report import JsonlLog


SCREENSHOT_SCHEDULE: tuple[tuple[float, str], ...] = tuple(
    (second, f"{second:03d}.png") for second in range(30, 300, 30)
)


class VisualModeError(RuntimeError):
    pass


def run_libvirt(arguments: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    command = " ".join(subprocess.list2cmdline([item]) for item in ["virsh", "--connect", "qemu:///system", *arguments])
    return subprocess.run(["sg", "libvirt", "-c", command], text=True, capture_output=True, timeout=timeout, check=False)


def require_visual_domain(domain: str) -> None:
    result = run_libvirt(["dumpxml", domain], timeout=10)
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or f"virsh exited {result.returncode}"
        raise VisualModeError(f"Unable to inspect domain {domain}: {reason}")
    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError as error:
        raise VisualModeError(f"Unable to inspect domain {domain}: invalid domain XML: {error}") from error
    graphics = root.find("./devices/graphics[@type='spice']")
    video = root.find("./devices/video")
    if graphics is None or video is None:
        raise VisualModeError(
            f"Visual mode requested, but domain {domain}\n"
            "has no graphical framebuffer.\n\n"
            "Instantiate/start the domain with --visual first."
        )
    clipboard = graphics.find("clipboard")
    filetransfer = graphics.find("filetransfer")
    prohibited = (
        root.find("./devices/filesystem") is not None
        or root.find("./devices/redirdev") is not None
        or any(
            channel.find("target") is not None
            and channel.find("target").get("name", "").startswith("com.redhat.spice")
            for channel in root.findall("./devices/channel")
        )
    )
    if (
        clipboard is None or clipboard.get("copypaste") != "no"
        or filetransfer is None or filetransfer.get("enable") != "no"
        or prohibited
    ):
        raise VisualModeError(
            f"Visual mode requested, but domain {domain} does not satisfy the restricted SPICE policy."
        )


class ScreenshotMonitor:
    """Best-effort host-side screenshots for a visual benchmark run."""

    def __init__(
        self,
        domain: str,
        run_dir: Path,
        orchestrator: JsonlLog,
        *,
        timeout_seconds: int,
        context: dict[str, object] | None = None,
        schedule: Sequence[tuple[float, str]] = SCREENSHOT_SCHEDULE,
    ) -> None:
        self.domain = domain
        self.directory = run_dir / "screenshots"
        self.orchestrator = orchestrator
        self.timeout_seconds = timeout_seconds
        self.context = context or {}
        self.schedule = schedule
        self.started_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def capture(self, filename: str) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / filename
        temporary = destination.with_name(destination.name + ".tmp")
        try:
            result = run_libvirt(["screenshot", self.domain, str(temporary)], timeout=10)
            if result.returncode != 0:
                reason = result.stderr.strip() or result.stdout.strip() or f"virsh exited {result.returncode}"
                raise RuntimeError(reason)
            os.replace(temporary, destination)
            self.orchestrator.emit("screenshot_captured", filename=filename, **self.context)
            return True
        except Exception as error:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            self.orchestrator.emit(
                "screenshot_failed", reason=str(error), filename=filename, **self.context,
            )
            return False

    def start(self) -> None:
        self.started_at = time.monotonic()
        self.capture("000-agent-start.png")
        self._thread = threading.Thread(target=self._run, name="benchmark-screenshots", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        for elapsed, filename in self.schedule:
            wait = max(0.0, self.started_at + elapsed - time.monotonic())
            if self._stop.wait(wait):
                return
            self.capture(filename)

    def finish_agent(self, *, timed_out: bool) -> None:
        self.stop()
        if timed_out:
            filename = f"{self.timeout_seconds:03d}-timeout.png"
        else:
            elapsed = max(0, round(time.monotonic() - self.started_at))
            filename = f"{elapsed:03d}-agent-exit.png"
        self.capture(filename)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def evaluator_before(self) -> None:
        elapsed = max(0, round(time.monotonic() - self.started_at))
        self.capture(f"{elapsed:03d}-evaluator-before.png")


def sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
