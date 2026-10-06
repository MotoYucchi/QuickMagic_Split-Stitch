"""Extended unit tests for splitting planner, capacity bounds, and resolution policies."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import pytest

from splitstitch.core.planner import plan_splitting
from splitstitch.core.probe import ProbeResult
from splitstitch.core.timebase import FrameTimeline


def make_dummy_probe(
    width: int = 1920,
    height: int = 1080,
    fps_num: int = 60,
    fps_den: int = 1,
    frame_count: int = 1800,
) -> ProbeResult:
    fps_frac = Fraction(fps_num, fps_den)
    dur = float(frame_count / fps_frac)
    tl = FrameTimeline.create_cfr(frame_count, fps_frac)
    return ProbeResult(
        path=Path("dummy.mp4"),
        size_bytes=10_000_000,
        width=width,
        height=height,
        rotation=0,
        fps=fps_frac,
        duration_sec=dur,
        frame_count=frame_count,
        first_pts_sec=0.0,
        pix_fmt="yuv420p",
        color_transfer="bt709",
        is_vfr=False,
        is_hdr=False,
        timeline=tl,
    )


def test_planner_ultra_long_video() -> None:
    """Verify planner handles ultra-long footage (2 hours at 60fps = 432,000 frames) efficiently and safely."""
    probe = make_dummy_probe(frame_count=432_000)
    out = plan_splitting(probe, plan_name="free", mode="stretch", overlap_sec=1.0)

    assert out.totals.chunk_count > 0
    assert out.chunks[0].source_start_frame == 0
    assert out.chunks[-1].source_end_frame == 432_000

    # Invariants check across all chunks
    for i in range(len(out.chunks) - 1):
        c_cur = out.chunks[i]
        c_next = out.chunks[i + 1]
        assert c_cur.source_end_frame > c_next.source_start_frame, "Adjacent chunks must overlap"
        assert c_cur.upload_frame_count <= out.max_allowed_chunk_frames


def test_resolution_policy_reject_low() -> None:
    """Verify 'reject-low' policy raises ValueError for resolutions below 1080p short side."""
    probe_low = make_dummy_probe(width=1280, height=720)
    with pytest.raises(ValueError, match="below minimum"):
        plan_splitting(probe_low, plan_name="free", resolution_policy="reject-low")


def test_resolution_policy_keep_and_scale() -> None:
    """Verify 'keep' policy guarantees 1080p floor without crashing."""
    probe_720p = make_dummy_probe(width=1280, height=720)
    out = plan_splitting(probe_720p, plan_name="free", resolution_policy="keep")
    # Guaranteed minimum short side is 1080
    assert min(out.plan_config.output_resolution) >= 1080


def test_resolution_policy_forced_1080_and_1440() -> None:
    """Verify forced resolution targets ('1080', '1440')."""
    probe_4k = make_dummy_probe(width=3840, height=2160)

    out_1080 = plan_splitting(probe_4k, plan_name="free", resolution_policy="1080")
    assert min(out_1080.plan_config.output_resolution) == 1080

    out_1440 = plan_splitting(probe_4k, plan_name="pro", resolution_policy="1440")
    assert min(out_1440.plan_config.output_resolution) == 1440


def test_all_plans_budget_planning() -> None:
    """Verify plan_splitting succeeds across all supported plans (free, basic, pro, max, studio)."""
    probe = make_dummy_probe(frame_count=3600)  # 60s of 60fps
    for plan in ["free", "basic", "pro", "max", "studio"]:
        out = plan_splitting(probe, plan_name=plan, mode="stretch")
        assert out.totals.chunk_count >= 1
        assert out.plan_config.name == plan
        assert out.estimated_size_per_chunk_mb > 0.0


def test_native_mode_downscales_fps_for_free_plan() -> None:
    """Verify native mode correctly assigns allowed FPS without stretching."""
    probe = make_dummy_probe(fps_num=60, frame_count=1800)
    out = plan_splitting(probe, plan_name="free", mode="native")
    # Free plan only allows 30fps
    assert out.plan_config.declared_fps == "30/1"
    assert out.plan_config.stretch_ratio == "1/1"
