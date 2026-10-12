"""FFmpeg argument builder (Shell-free pure functions)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import List, Optional

from splitstitch.core.manifest import ChunkInfo, PlanConfig
from splitstitch.core.probe import ProbeResult, get_ffmpeg_path
from splitstitch.core.timebase import parse_fraction


def build_ffmpeg_chunk_cmd(
    probe: ProbeResult,
    chunk: ChunkInfo,
    plan_config: PlanConfig,
    output_path: Path | str,
    session_id: str,
    custom_ffmpeg_path: Optional[str] = None,
) -> List[str]:
    """Build exact ffmpeg command arguments for slicing and encoding a chunk."""
    ffmpeg_bin = custom_ffmpeg_path or get_ffmpeg_path()
    out_p = Path(output_path).resolve()

    start_frame = chunk.source_start_frame
    end_frame = chunk.source_end_frame

    declared_fps = parse_fraction(plan_config.declared_fps)
    fd_str = f"{declared_fps.numerator}/{declared_fps.denominator}"

    target_w, target_h = plan_config.output_resolution

    # Video Filter chain
    filters: List[str] = []

    # Frame slicing strategy:
    # 1. For chunk 1 (start_frame == 0): Start from video beginning without seeking or trim-start
    #    to eliminate any initial PTS jitter or container offset issues.
    # 2. For chunks > 1: Seek with -copyts so presentation timestamps remain absolute,
    #    then trim starting at the midpoint between (start_frame - 1) and start_frame.
    # 3. We NEVER specify 'trim=end=...' because floating-point timestamp rounding or non-integer
    #    FPS (e.g. 59.94, 59.999, 23.976, VFR) can cause FFmpeg to drop the last 1-2 frames prematurely.
    #    Instead, exact frame count is strictly and deterministically bounded by '-frames:v'.
    seek_args: List[str] = []
    if start_frame > 0:
        t_start = probe.timeline.get_time(start_frame)
        t_prev = probe.timeline.get_time(start_frame - 1)
        trim_start_time = (t_prev + t_start) / 2.0
        lead_in = 2.0
        seek_sec = max(0.0, t_start - lead_in)
        seek_args = ["-ss", f"{seek_sec:.6f}", "-copyts"]
        filters.append(f"trim=start={trim_start_time:.6f}")

    # Re-timestamp frames sequentially to 1/declared_fps interval
    filters.append(f"setpts=N/({fd_str}*TB)")

    # Autorotate if needed (ffmpeg default handles displaymatrix, but normalize filter ensures it)
    if abs(probe.rotation) != 0:
        filters.append("autorotate")

    # Color tone mapping if HDR
    if probe.is_hdr:
        filters.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709:m=bt709:t=bt709,tonemap=tonemap=hable")

    # Scale filter preserving aspect ratio with Lanczos
    filters.append(f"scale={target_w}:{target_h}:flags=lanczos")

    # Normalize pixel format
    filters.append("format=yuv420p")

    vf_chain = ",".join(filters)

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-progress", "pipe:1",
        *seek_args,
        "-i", str(probe.path),
        "-map", "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf", vf_chain,
        "-fps_mode", "passthrough",
        "-frames:v", str(chunk.upload_frame_count),
        "-c:v", plan_config.encode.codec,
        "-preset", plan_config.encode.preset,
        "-crf", str(plan_config.encode.crf),
        "-maxrate", f"{plan_config.encode.maxrate_kbps}k",
        "-bufsize", f"{plan_config.encode.bufsize_kbps}k",
        "-profile:v", "high",
        "-level:v", "4.2",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-movflags", "+faststart",
        "-metadata", f"comment=splitstitch:{session_id}:{chunk.index}",
        str(out_p),
    ]

    return cmd
