"""Property-based tests for chunk planner mathematical invariants."""

from fractions import Fraction
from pathlib import Path
from hypothesis import given, settings, strategies as st
import pytest

from splitstitch.core.planner import plan_splitting
from splitstitch.core.probe import ProbeResult
from splitstitch.core.timebase import FrameTimeline


@settings(max_examples=50, deadline=None)
@given(
    frame_count=st.integers(min_value=30, max_value=10000),
    fps_val=st.sampled_from([Fraction(24, 1), Fraction(30, 1), Fraction(60000, 1001), Fraction(60, 1), Fraction(120, 1)]),
    plan_name=st.sampled_from(["free", "basic", "pro", "max"]),
    mode=st.sampled_from(["stretch", "native"]),
)
def test_planner_invariants(frame_count: int, fps_val: Fraction, plan_name: str, mode: str) -> None:
    # Construct mock ProbeResult
    tl = FrameTimeline.create_cfr(frame_count, fps_val)
    probe = ProbeResult(
        path=Path("dummy.mp4"),
        size_bytes=10_000_000,
        width=1920,
        height=1080,
        rotation=0,
        fps=fps_val,
        is_vfr=False,
        frame_count=frame_count,
        duration_sec=float(frame_count / fps_val),
        first_pts_sec=0.0,
        pix_fmt="yuv420p",
        color_transfer="bt709",
        is_hdr=False,
        timeline=tl,
    )

    out = plan_splitting(
        probe=probe,
        plan_name=plan_name,
        mode=mode,
        resolution_policy="auto",
        quality_preset="high",
        overlap_sec=1.0,
    )

    chunks = out.chunks
    assert len(chunks) >= 1

    # Invariant 1: First chunk starts at 0
    assert chunks[0].source_start_frame == 0

    # Invariant 2: Last chunk ends at total frames
    assert chunks[-1].source_end_frame == frame_count

    # Invariant 3: Capacity bounds - no chunk exceeds maximum capacity
    for c in chunks:
        assert c.upload_frame_count <= out.max_allowed_chunk_frames

    # Invariant 4: Continuous coverage and overlap invariants
    for i in range(len(chunks) - 1):
        c_cur = chunks[i]
        c_next = chunks[i + 1]
        overlap_len = c_cur.source_end_frame - c_next.source_start_frame
        assert overlap_len >= out.overlap_config.source_frames or c_next.source_end_frame == frame_count
        assert c_next.source_start_frame < c_cur.source_end_frame
