"""ffprobe video stream analyzer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import List, Optional, Tuple

from splitstitch.core.timebase import FrameTimeline, parse_fraction


@dataclass
class ProbeResult:
    path: Path
    size_bytes: int
    width: int
    height: int
    rotation: int
    fps: Fraction
    is_vfr: bool
    frame_count: int
    duration_sec: float
    first_pts_sec: float
    pix_fmt: str
    color_transfer: str
    is_hdr: bool
    timeline: FrameTimeline

    @property
    def display_width(self) -> int:
        return self.height if abs(self.rotation) in (90, 270) else self.width

    @property
    def display_height(self) -> int:
        return self.width if abs(self.rotation) in (90, 270) else self.height

    @property
    def short_side(self) -> int:
        return min(self.display_width, self.display_height)

    @property
    def long_side(self) -> int:
        return max(self.display_width, self.display_height)


def get_ffprobe_path() -> str:
    """Find ffprobe binary."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    # Check local bin
    local_bin = Path.home() / ".local" / "bin" / "ffprobe"
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    raise FileNotFoundError("ffprobe not found in PATH or ~/.local/bin")


def get_ffmpeg_path() -> str:
    """Find ffmpeg binary."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    local_bin = Path.home() / ".local" / "bin" / "ffmpeg"
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    raise FileNotFoundError("ffmpeg not found in PATH or ~/.local/bin")


def probe_video(video_path: Path | str, fast: bool = False) -> ProbeResult:
    """Probe video file using ffprobe with rotation, HDR, VFR, and frame-rate detection."""
    path = Path(video_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    size_bytes = path.stat().st_size
    ffprobe = get_ffprobe_path()

    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(res.stdout)

    video_stream = None
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            video_stream = s
            break

    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    # Detect rotation
    rotation = 0
    # 1. From side_data_list
    for side in video_stream.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(side["rotation"])
            break
    # 2. From tags
    if rotation == 0:
        tags = video_stream.get("tags", {})
        if "rotate" in tags:
            try:
                rotation = int(tags["rotate"])
            except ValueError:
                pass

    # FPS extraction
    r_fps_str = video_stream.get("r_frame_rate", "30/1")
    avg_fps_str = video_stream.get("avg_frame_rate", "30/1")

    r_fps = parse_fraction(r_fps_str) if r_fps_str != "0/0" else Fraction(30, 1)
    avg_fps = parse_fraction(avg_fps_str) if avg_fps_str != "0/0" else r_fps

    # Color & HDR
    pix_fmt = video_stream.get("pix_fmt", "yuv420p")
    color_transfer = video_stream.get("color_transfer", "bt709")
    hdr_transfers = {"smpte2084", "arib-std-b67", "smpte428"}
    is_hdr = (color_transfer in hdr_transfers) or ("10le" in pix_fmt)

    # Duration & frame count
    format_dur = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    stream_dur = float(video_stream.get("duration", 0.0) or format_dur)
    duration_sec = stream_dur if stream_dur > 0 else format_dur

    nb_frames_str = video_stream.get("nb_frames")
    nb_frames = int(nb_frames_str) if nb_frames_str and nb_frames_str.isdigit() else 0

    first_pts = float(video_stream.get("start_time", 0.0) or 0.0)

    # Detailed PTS collection if fast is False or frame count is unknown
    pts_list: List[float] = []
    if not fast:
        pts_cmd = [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,duration_time",
            "-of", "csv=p=0",
            str(path),
        ]
        pts_res = subprocess.run(pts_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in pts_res.stdout.strip().splitlines():
            parts = line.split(",")
            if parts and parts[0]:
                try:
                    pts_list.append(float(parts[0]))
                except ValueError:
                    pass

    if pts_list:
        timeline = FrameTimeline.create_vfr(pts_list, nominal_fps=r_fps)
        frame_count = len(pts_list)
        first_pts = pts_list[0]
        is_vfr = timeline.is_vfr
        fps = timeline.nominal_fps
    else:
        if nb_frames == 0 and duration_sec > 0:
            nb_frames = int(round(duration_sec * float(r_fps)))
        timeline = FrameTimeline.create_cfr(nb_frames, r_fps, start_pts=first_pts)
        frame_count = nb_frames
        fps = r_fps
        is_vfr = False

    return ProbeResult(
        path=path,
        size_bytes=size_bytes,
        width=width,
        height=height,
        rotation=rotation,
        fps=fps,
        is_vfr=is_vfr,
        frame_count=frame_count,
        duration_sec=duration_sec,
        first_pts_sec=first_pts,
        pix_fmt=pix_fmt,
        color_transfer=color_transfer,
        is_hdr=is_hdr,
        timeline=timeline,
    )
