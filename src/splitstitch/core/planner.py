"""Chunk segmentation and resource budget planner (Pure logic)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, List, Optional, Tuple

import yaml

from splitstitch.core.manifest import ChunkInfo, EncodeParams, OverlapConfig, PlanConfig, SessionTotals
from splitstitch.core.probe import ProbeResult
from splitstitch.core.timebase import format_fraction, parse_fraction


@dataclass
class PlanSpec:
    name: str
    display_name: str
    allowed_fps: List[Fraction]
    max_duration_sec: dict[Fraction, float]
    max_size_bytes: int
    export_formats: List[str]


def load_plans_config(config_path: Optional[Path | str] = None) -> dict[str, Any]:
    """Load plans.yaml from default or specified path."""
    if config_path is None:
        p = Path(__file__).resolve().parent.parent / "config" / "plans.yaml"
    else:
        p = Path(config_path)

    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_plan_spec(plan_name: str, config: Optional[dict[str, Any]] = None) -> PlanSpec:
    """Retrieve PlanSpec for given plan name."""
    cfg = config or load_plans_config()
    plans = cfg.get("plans", {})
    name_clean = plan_name.lower().strip()
    if name_clean not in plans:
        raise ValueError(f"Unknown plan: '{plan_name}'. Available: {list(plans.keys())}")

    raw = plans[name_clean]
    allowed_fps = [parse_fraction(f) for f in raw["allowed_fps"]]
    max_dur = {parse_fraction(k): float(v) for k, v in raw["max_duration_sec"].items()}
    max_size_mb = raw["max_size_mb"]
    size_unit = cfg.get("size_unit", "decimal")
    max_size_bytes = max_size_mb * (1000 * 1000 if size_unit == "decimal" else 1024 * 1024)

    return PlanSpec(
        name=name_clean,
        display_name=raw.get("display_name", plan_name.title()),
        allowed_fps=allowed_fps,
        max_duration_sec=max_dur,
        max_size_bytes=max_size_bytes,
        export_formats=raw.get("export_formats", ["fbx"]),
    )


@dataclass
class PlannerOutput:
    plan_config: PlanConfig
    overlap_config: OverlapConfig
    chunks: List[ChunkInfo]
    totals: SessionTotals
    max_allowed_chunk_frames: int
    bitrate_kbps: int
    estimated_size_per_chunk_mb: float


def plan_splitting(
    probe: ProbeResult,
    plan_name: str = "free",
    mode: str = "stretch",  # "stretch" or "native"
    resolution_policy: str = "auto",  # "auto", "keep", "1080", "1440", "reject-low"
    quality_preset: str = "high",  # "high", "balanced", "compact"
    overlap_sec: float = 1.0,
    plans_config: Optional[dict[str, Any]] = None,
) -> PlannerOutput:
    """Calculate exact chunk split plan adhering to mathematically proven capacity bounds."""
    cfg = plans_config or load_plans_config()
    spec = get_plan_spec(plan_name, cfg)
    safety_factor = float(cfg.get("safety_factor", 0.95))
    duration_margin = float(cfg.get("duration_margin_sec", 0.1))
    min_short_side = int(cfg.get("min_short_side", 1080))

    src_fps = probe.fps
    src_frames = probe.frame_count

    # 1. Output Resolution calculation
    orig_w, orig_h = probe.display_width, probe.display_height
    short_dim = min(orig_w, orig_h)
    long_dim = max(orig_w, orig_h)
    is_portrait = orig_h > orig_w

    if resolution_policy == "reject-low":
        if short_dim < min_short_side:
            raise ValueError(f"Video resolution short side ({short_dim}px) is below minimum {min_short_side}px.")
        target_short = short_dim
    elif resolution_policy == "keep":
        target_short = max(short_dim, min_short_side)
    elif resolution_policy in ("1080", "1440"):
        target_short = int(resolution_policy)
    else:  # "auto"
        # Guarantee 1080p minimum short side, but avoid unnecessary giant resolution
        target_short = max(short_dim, min_short_side)
        if target_short > 1440 and plan_name == "free":
            target_short = 1080  # Scale 4K down on Free plan to optimize capacity and chunk count

    # Compute even dimensions preserving aspect ratio
    scale_factor = target_short / short_dim
    target_long = int(round(long_dim * scale_factor / 2.0)) * 2
    target_w, target_h = (target_short, target_long) if is_portrait else (target_long, target_short)

    # 2. Select Declared FPS and Stretch Ratio
    if mode == "stretch":
        # Find declared FPS that minimizes |log(src_fps / f_d)|
        best_fd = spec.allowed_fps[0]
        best_diff = abs(math.log(float(src_fps) / float(best_fd)))
        for f in spec.allowed_fps:
            diff = abs(math.log(float(src_fps) / float(f)))
            if diff < best_diff or (abs(diff - best_diff) < 1e-6 and f < best_fd):
                best_diff = diff
                best_fd = f
        declared_fps = best_fd
        stretch_ratio = src_fps / declared_fps
    else:
        # Native mode: match if allowed, else downscale fps
        if src_fps in spec.allowed_fps:
            declared_fps = src_fps
        else:
            # Pick largest allowed fps <= src_fps, else minimum allowed
            eligible = [f for f in spec.allowed_fps if f <= src_fps]
            declared_fps = max(eligible) if eligible else min(spec.allowed_fps)
        stretch_ratio = Fraction(1, 1)

    # 3. Bitrate budget & VBV bounds calculation
    # Base bitrate at 1080p: high=400kbit/frame (12Mbps@30fps), balanced=280, compact=200
    base_b_f = {"high": 400.0, "balanced": 280.0, "compact": 200.0}.get(quality_preset, 400.0)
    crf_val = {"high": 18, "balanced": 20, "compact": 22}.get(quality_preset, 18)

    # Scale bitrate by (pixel_count / (1920*1080))^0.75
    pixel_ratio = (target_w * target_h) / (1920.0 * 1080.0)
    b_f_kbit = base_b_f * (pixel_ratio**0.75)  # kbits per frame
    maxrate_kbps = int(round(b_f_kbit * float(declared_fps)))
    bufsize_kbps = maxrate_kbps  # 1-second VBV buffer

    # 4. Chunk duration upper bounds
    max_plan_dur = spec.max_duration_sec.get(declared_fps, 30.0)
    L_dur = int(math.floor((max_plan_dur - duration_margin) * float(declared_fps)))

    # Capacity upper bound in frames:
    # total_bits <= maxrate * (L / declared_fps) + bufsize <= safety * max_size_bits
    max_size_kbits = (spec.max_size_bytes * 8.0 * safety_factor) / 1000.0
    container_overhead_kbits = 800.0  # 100 KB estimated container overhead
    L_size = int(math.floor((max_size_kbits - bufsize_kbps - container_overhead_kbits) / b_f_kbit))

    max_chunk_frames = max(1, min(L_dur, L_size))

    # Overlap frames in source timeline
    overlap_frames = int(round(overlap_sec * float(src_fps)))
    if overlap_frames >= max_chunk_frames:
        overlap_frames = max(1, max_chunk_frames // 4)

    min_unique_frames = int(round(1.0 * float(src_fps)))  # at least 1s unique per chunk
    if max_chunk_frames - overlap_frames < min_unique_frames:
        raise ValueError(
            f"Cannot split: max chunk capacity ({max_chunk_frames} frames) with overlap ({overlap_frames} frames) "
            f"leaves less than 1.0s unique footage."
        )

    # 5. Equalized chunk segmentation calculation
    N = src_frames
    L = max_chunk_frames
    O = overlap_frames

    if N <= L:
        num_chunks = 1
        chunk_ranges = [(0, N)]
    else:
        num_chunks = max(1, math.ceil((N - O) / (L - O)))
        L_star = math.ceil((N + (num_chunks - 1) * O) / num_chunks)
        P = L_star - O
        chunk_ranges = []
        for i in range(num_chunks):
            start = i * P
            end = min(start + L_star, N)
            chunk_ranges.append((start, end))

    # Guard and blend frame budget
    guard_upload = 8
    blend_source = max(2, int(round(0.5 * float(src_fps))))

    # Build ChunkInfo objects
    chunks: List[ChunkInfo] = []
    total_upload_frames = 0
    total_upload_sec = 0.0

    for idx, (c_start, c_end) in enumerate(chunk_ranges, start=1):
        f_count = c_end - c_start
        u_dur = f_count / float(declared_fps)
        total_upload_frames += f_count
        total_upload_sec += u_dur

        c_info = ChunkInfo(
            index=idx,
            filename=f"chunk_{idx:03d}of{num_chunks:03d}.mp4",
            source_frame_range=(c_start, c_end),
            upload_frame_count=f_count,
            upload_duration_sec=round(u_dur, 3),
            size_bytes=0,
            status="planned",
        )
        chunks.append(c_info)

    # Invariants verification
    assert chunks[0].source_start_frame == 0, "First chunk must start at frame 0"
    assert chunks[-1].source_end_frame == N, "Last chunk must end at frame N"
    for i in range(len(chunks) - 1):
        overlap_len = chunks[i].source_end_frame - chunks[i + 1].source_start_frame
        assert overlap_len >= O or chunks[i + 1].source_end_frame == N, "Overlap invariant violated"
    for c in chunks:
        assert c.upload_frame_count <= L, f"Chunk {c.index} exceeds max capacity {L}"

    plan_cfg = PlanConfig(
        name=spec.name,
        mode=mode,
        declared_fps=format_fraction(declared_fps),
        stretch_ratio=format_fraction(stretch_ratio),
        resolution_policy=resolution_policy,
        output_resolution=(target_w, target_h),
        quality_preset=quality_preset,
        encode=EncodeParams(
            codec="libx264",
            crf=crf_val,
            maxrate_kbps=maxrate_kbps,
            bufsize_kbps=bufsize_kbps,
            preset="slow",
        ),
    )

    overlap_cfg = OverlapConfig(
        source_frames=O,
        guard_upload_frames=guard_upload,
        blend_source_frames=blend_source,
    )

    totals = SessionTotals(
        chunk_count=num_chunks,
        upload_seconds=round(total_upload_sec, 2),
        upload_bytes=0,
    )

    est_mb = (maxrate_kbps * (L / float(declared_fps)) + bufsize_kbps) / 8000.0

    return PlannerOutput(
        plan_config=plan_cfg,
        overlap_config=overlap_cfg,
        chunks=chunks,
        totals=totals,
        max_allowed_chunk_frames=L,
        bitrate_kbps=maxrate_kbps,
        estimated_size_per_chunk_mb=round(est_mb, 2),
    )
