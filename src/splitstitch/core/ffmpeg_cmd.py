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

    # Retrieve exact PTS for start and end from timeline
    t_start = probe.timeline.get_time(start_frame)
    t_end = probe.timeline.get_time(end_frame)

    # Input seek with safety lead-in (2.0s before start frame) for fast keyframe decoding
    lead_in = 2.0
    seek_sec = max(0.0, t_start - lead_in)
    rel_start_pts = t_start - seek_sec
    rel_end_pts = t_end - seek_sec

    declared_fps = parse_fraction(plan_config.declared_fps)
    fd_str = f"{declared_fps.numerator}/{declared_fps.denominator}"

    target_w, target_h = plan_config.output_resolution

    # Video Filter chain
    filters: List[str] = []

    # 1. Precise trim filter based on relative seconds
    filters.append(f"trim=start={rel_start_pts:.6f}:end={rel_end_pts:.6f}")

    # 2. Strict frame re-timestamping: N / (FD * TB)
    # This guarantees 1:1 input-frame to output-frame mapping without duplicate or dropped frames
    filters.append(f"setpts=N/({fd_str}*TB)")

    # 3. Autorotate if needed (ffmpeg default handles displaymatrix, but normalize filter ensures it)
    if abs(probe.rotation) != 0:
        filters.append("autorotate")

    # 4. Color tone mapping if HDR
    if probe.is_hdr:
        filters.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709:m=bt709:t=bt709,tonemap=tonemap=hable")

    # 5. Scale filter preserving aspect ratio with Lanczos
    filters.append(f"scale={target_w}:{target_h}:flags=lanczos")

    # 6. Normalize pixel format
    filters.append("format=yuv420p")

    vf_chain = ",".join(filters)

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-progress", "pipe:1",
        "-ss", f"{seek_sec:.6f}",
        "-i", str(probe.path),
        "-map", "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf", vf_chain,
        "-r", fd_str,
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
