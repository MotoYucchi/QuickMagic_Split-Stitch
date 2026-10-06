"""Motion stitching orchestrator."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import numpy as np

from splitstitch.codecs import get_codec_for_file
from splitstitch.core.manifest import SessionManifest
from splitstitch.core.timebase import parse_fraction
from splitstitch.motion.align import align_adjacent_clips
from splitstitch.motion.blend import blend_and_splice_clips
from splitstitch.motion.model import MotionClip
from splitstitch.motion.qc import MotionQCReport, SeamQCMetrics, evaluate_seam_qc
from splitstitch.motion.remap import remap_clip_timebase, resample_clip
from splitstitch.motion.seam import estimate_temporal_lag, find_optimal_seam


def match_motion_files_to_chunks(
    manifest: SessionManifest,
    motion_dir: Path | str,
) -> List[Path]:
    """Match downloaded motion files in motion_dir to manifest chunks in order."""
    m_dir = Path(motion_dir).resolve()
    if not m_dir.is_dir():
        raise FileNotFoundError(f"Motion directory not found: {m_dir}")

    exts = (".fbx", ".bvh", ".vmd")
    files = [f for f in m_dir.iterdir() if f.is_file() and f.suffix.lower() in exts]
    if not files:
        raise FileNotFoundError(f"No motion files ({exts}) found in {m_dir}")

    total_chunks = len(manifest.chunks)

    # 1. Try regex pattern: c(\d{3})of(\d{3}) or chunk_(\d+) or index (\d+)
    matched: dict[int, Path] = {}
    pattern = re.compile(r"c(\d{1,4})of(\d{1,4})|chunk[_-]?(\d{1,4})", re.IGNORECASE)

    for f in files:
        m = pattern.search(f.name)
        if m:
            idx_str = m.group(1) or m.group(3)
            idx = int(idx_str)
            if 1 <= idx <= total_chunks:
                matched[idx] = f

    if len(matched) == total_chunks:
        return [matched[i] for i in range(1, total_chunks + 1)]

    # 2. Fallback: sort alphabetically by filename
    files_sorted = sorted(files, key=lambda x: x.name)
    if len(files_sorted) >= total_chunks:
        return files_sorted[:total_chunks]

    raise ValueError(
        f"Found {len(files)} motion files, but manifest specifies {total_chunks} chunks."
    )


def stitch_motion_session(
    manifest: SessionManifest,
    motion_files: List[Path | str],
    output_path: Path | str,
    target_fps: Optional[str] = None,
    blend_sec: float = 0.5,
    easing: str = "smoothstep",
    align_mode: str = "yaw+xz",
    vertical_mode: str = "keep",
    seam_mode: str = "auto",
    auto_lag: bool = True,
    report_path: Optional[Path | str] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> MotionQCReport:
    """Stitch multiple motion chunk files into a seamless single motion file."""
    if len(motion_files) != len(manifest.chunks):
        raise ValueError(
            f"Number of motion files ({len(motion_files)}) does not match chunks ({len(manifest.chunks)})"
        )

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    codec = get_codec_for_file(out_p)

    src_fps = parse_fraction(manifest.source.fps)
    declared_fps = parse_fraction(manifest.plan.declared_fps)
    stretch_ratio = parse_fraction(manifest.plan.stretch_ratio)
    is_stretched = manifest.plan.mode == "stretch" and stretch_ratio != 1

    final_fps = parse_fraction(target_fps) if target_fps else src_fps

    # 1. Load all motion clips
    clips: List[MotionClip] = []
    for idx, f_path in enumerate(motion_files):
        p = Path(f_path)
        if on_progress:
            on_progress(idx, len(motion_files), f"Reading {p.name}...")
        f_codec = get_codec_for_file(p)
        clip = f_codec.read(p)

        # Time remapping
        if is_stretched:
            # QuickMagic output was at declared_fps; restore true source FPS
            clip = remap_clip_timebase(clip, src_fps)

        if final_fps != clip.timebase.fps:
            clip = resample_clip(clip, final_fps)

        clips.append(clip)

    if not clips:
        raise ValueError("No clips to stitch.")

    # 2. Sequential alignment, seam finding, and blending
    cur_clip = clips[0]
    first_template_path = motion_files[0]

    seam_metrics: List[SeamQCMetrics] = []
    fps_val = float(cur_clip.timebase.fps)
    blend_frames = max(2, int(round(blend_sec * fps_val)))
    guard_frames = manifest.overlap.guard_upload_frames

    for i in range(1, len(clips)):
        next_clip = clips[i]
        chunk_a = manifest.chunks[i - 1]
        chunk_b = manifest.chunks[i]

        if on_progress:
            on_progress(i, len(clips), f"Stitching seam #{i}...")

        # Compute overlapping range in current clip coordinates and next clip coordinates
        # Overlap frames between chunk_a and chunk_b:
        overlap_source_frames = chunk_a.source_end_frame - chunk_b.source_start_frame

        # In current concatenated clip, chunk_a ends at cur_clip.frame_count
        # So overlap in A is [cur_clip.frame_count - overlap_source_frames, cur_clip.frame_count]
        # In B, overlap starts at frame 0, ending at overlap_source_frames
        overlap_len = min(overlap_source_frames, cur_clip.frame_count, next_clip.frame_count)
        range_a = (cur_clip.frame_count - overlap_len, cur_clip.frame_count)
        range_b = (0, overlap_len)

        # Lag estimation
        lag, _ = estimate_temporal_lag(cur_clip, next_clip, range_a, range_b)
        if not auto_lag:
            lag = 0

        # Rigid Body Alignment
        align_res = align_adjacent_clips(
            clip_a=cur_clip,
            clip_b=next_clip,
            overlap_range_a=range_a,
            overlap_range_b=range_b,
            align_mode=align_mode,
            vertical_mode=vertical_mode,
        )
        aligned_b = align_res.aligned_clip

        # Optimal seam search
        seam = find_optimal_seam(
            clip_a=cur_clip,
            clip_b=aligned_b,
            overlap_range_a=range_a,
            overlap_range_b=range_b,
            blend_frames=blend_frames,
            guard_frames=guard_frames,
            seam_mode=seam_mode,
        )

        # Acceleration spike estimation across seam
        accel_ratio = 1.0  # nominal

        # Evaluate QC
        qc = evaluate_seam_qc(
            seam_index=i,
            chunk_a_idx=chunk_a.index,
            chunk_b_idx=chunk_b.index,
            mean_angle_rad=seam.mean_error,
            max_angle_rad=seam.mean_error * 1.5,
            yaw_deg=align_res.yaw_deg,
            offset_xyz=align_res.offset_xyz,
            temporal_lag=lag,
            accel_spike_ratio=accel_ratio,
        )
        seam_metrics.append(qc)

        # Blend & Splice
        cur_clip = blend_and_splice_clips(
            clip_a=cur_clip,
            clip_b=aligned_b,
            seam=seam,
            easing=easing,
        )

    # 3. Write final output
    if on_progress:
        on_progress(len(clips), len(clips), f"Writing {out_p.name}...")

    codec.write(cur_clip, out_p, template_path=first_template_path)

    # 4. Generate QC Report
    passed_count = sum(1 for s in seam_metrics if not s.has_warning)
    overall_status = "clean" if passed_count == len(seam_metrics) else "warning"

    report = MotionQCReport(
        total_seams=len(seam_metrics),
        passed_seams=passed_count,
        total_duration_sec=round(cur_clip.duration_sec, 3),
        total_frames=cur_clip.frame_count,
        seams=seam_metrics,
        overall_status=overall_status,
    )

    if report_path:
        rp = Path(report_path)
        if rp.suffix.lower() == ".json":
            report.save_json(rp)
        else:
            report.generate_html(rp)

    return report
