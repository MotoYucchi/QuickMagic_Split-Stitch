"""FFmpeg execution runner with progress parsing and graceful cancellation."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class EncodeProgress:
    current_frame: int
    total_frames: int
    fps: float
    speed: str
    percent: float


ProgressCallback = Callable[[EncodeProgress], None]


class EncodeError(RuntimeError):
    def __init__(self, message: str, return_code: int, stderr_tail: str) -> None:
        super().__init__(f"{message} (code {return_code}):\n{stderr_tail}")
        self.return_code = return_code
        self.stderr_tail = stderr_tail


def run_ffmpeg_encode(
    cmd: List[str],
    total_frames: int,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    """Execute FFmpeg command, parsing progress output from stdout."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    stderr_lines: List[str] = []

    def read_stderr() -> None:
        if proc.stderr:
            for line in proc.stderr:
                stderr_lines.append(line)
                if len(stderr_lines) > 50:
                    stderr_lines.pop(0)

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    cur_frame = 0
    cur_fps = 0.0
    cur_speed = "1.0x"

    try:
        if proc.stdout:
            for raw_line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    raise InterruptedError("Encoding canceled by user.")

                line = raw_line.strip()
                if not line:
                    continue

                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()

                    if key == "frame":
                        try:
                            cur_frame = int(val)
                        except ValueError:
                            pass
                    elif key == "fps":
                        try:
                            cur_fps = float(val)
                        except ValueError:
                            pass
                    elif key == "speed":
                        cur_speed = val
                    elif key == "progress":
                        if on_progress and total_frames > 0:
                            pct = min(100.0, (cur_frame / total_frames) * 100.0)
                            on_progress(
                                EncodeProgress(
                                    current_frame=cur_frame,
                                    total_frames=total_frames,
                                    fps=cur_fps,
                                    speed=cur_speed,
                                    percent=pct,
                                )
                            )

        proc.wait()
        stderr_thread.join(timeout=2)

        if proc.returncode != 0:
            tail = "".join(stderr_lines)
            raise EncodeError("FFmpeg execution failed", proc.returncode, tail)

    except Exception:
        if proc.poll() is None:
            proc.kill()
        raise
