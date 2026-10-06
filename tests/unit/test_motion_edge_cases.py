"""Edge-case and resilience unit tests for motion alignment, seam selection, and QC."""

from __future__ import annotations

import math
from pathlib import Path
import numpy as np
import pytest

from splitstitch.core.timebase import TimeBase
from splitstitch.motion.align import align_adjacent_clips
from splitstitch.motion.model import MotionClip, Skeleton
from splitstitch.motion.qc import MotionQCReport, SeamQCMetrics
from splitstitch.motion.quat import make_yaw_quat
from splitstitch.motion.seam import estimate_temporal_lag, find_optimal_seam


def make_test_clip(frame_count: int, offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0), yaw_deg: float = 0.0) -> MotionClip:
    names = ["Hips", "Spine"]
    parents = np.array([-1, 0], dtype=np.int32)
    offsets = np.array([[0, 0, 0], [0, 1, 0]], dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, root_index=0)

    timebase = TimeBase.from_fps(30)
    local_rot = np.zeros((frame_count, 2, 4), dtype=np.float64)
    local_rot[..., 3] = 1.0

    q_yaw = make_yaw_quat(math.radians(yaw_deg))
    for f in range(frame_count):
        local_rot[f, 0, :] = q_yaw

    root_pos = np.zeros((frame_count, 3), dtype=np.float64)
    ox, oy, oz = offset_xyz
    for f in range(frame_count):
        root_pos[f, :] = [ox + f * 0.05, oy, oz + f * 0.02]

    return MotionClip(skeleton=skeleton, timebase=timebase, local_rot=local_rot, root_pos=root_pos)


def test_alignment_vertical_keep_vs_align() -> None:
    """Verify vertical_mode behavior ('keep' leaves Y untouched, 'align' offsets Y)."""
    # Clip A at Y=1.0, Clip B at Y=1.5
    clip_a = make_test_clip(40, offset_xyz=(0.0, 1.0, 0.0))
    clip_b = make_test_clip(40, offset_xyz=(0.0, 1.5, 0.0))

    # Mode: keep (default)
    res_keep = align_adjacent_clips(
        clip_a, clip_b,
        overlap_range_a=(20, 40),
        overlap_range_b=(0, 20),
        align_mode="yaw+xz",
        vertical_mode="keep",
    )
    # In keep mode, Y offset correction must be exactly 0.0
    assert res_keep.offset_xyz[1] == 0.0
    assert res_keep.aligned_clip.root_pos[0, 1] == pytest.approx(1.5)

    # Mode: align
    res_align = align_adjacent_clips(
        clip_a, clip_b,
        overlap_range_a=(20, 40),
        overlap_range_b=(0, 20),
        align_mode="yaw+xz",
        vertical_mode="align",
    )
    # In align mode, Y offset should be -0.5 to bring Clip B from 1.5 down to 1.0
    assert res_align.offset_xyz[1] == pytest.approx(-0.5, abs=1e-3)
    assert res_align.aligned_clip.root_pos[0, 1] == pytest.approx(1.0, abs=1e-3)


def test_alignment_none_and_xz() -> None:
    """Verify align_mode 'none' skips changes and 'xz' preserves original yaw."""
    clip_a = make_test_clip(30, yaw_deg=0.0)
    clip_b = make_test_clip(30, offset_xyz=(10.0, 0.0, 5.0), yaw_deg=25.0)

    # align_mode = "none"
    res_none = align_adjacent_clips(
        clip_a, clip_b,
        overlap_range_a=(15, 30),
        overlap_range_b=(0, 15),
        align_mode="none",
    )
    assert res_none.yaw_deg == 0.0
    assert np.allclose(res_none.offset_xyz, [0.0, 0.0, 0.0])

    # align_mode = "xz" (no yaw rotation)
    res_xz = align_adjacent_clips(
        clip_a, clip_b,
        overlap_range_a=(15, 30),
        overlap_range_b=(0, 15),
        align_mode="xz",
    )
    assert res_xz.yaw_deg == 0.0
    assert not np.allclose(res_xz.offset_xyz, [0.0, 0.0, 0.0])


def test_seam_mode_center() -> None:
    """Verify seam_mode='center' falls back to geometric middle of overlap range."""
    clip_a = make_test_clip(50)
    clip_b = make_test_clip(50)

    seam = find_optimal_seam(
        clip_a, clip_b,
        overlap_range_a=(30, 50),
        overlap_range_b=(0, 20),
        blend_frames=6,
        seam_mode="center",
    )
    # Overlap length is 20 frames. Center relative is 10.
    assert seam.optimal_center_a == 30 + 10
    assert seam.optimal_center_b == 0 + 10
    assert seam.blend_start_a == 40 - 3
    assert seam.blend_end_a == 40 + 3


def test_estimate_temporal_lag() -> None:
    """Verify estimate_temporal_lag identifies introduced temporal lag."""
    F = 60
    clip_a = make_test_clip(F)

    # Create Clip B where movement is lagged by 2 frames relative to A
    names = ["Hips", "Spine"]
    parents = np.array([-1, 0], dtype=np.int32)
    offsets = np.array([[0, 0, 0], [0, 1, 0]], dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, root_index=0)

    # Clip B with 2 frames positive shift
    root_pos_b = np.zeros((F, 3), dtype=np.float64)
    for f in range(F):
        # Frame f of B corresponds to movement of frame (f - 2)
        root_pos_b[f, :] = [(f - 2) * 0.05, 0.0, 0.0]

    clip_b = MotionClip(
        skeleton=skeleton,
        timebase=TimeBase.from_fps(30),
        local_rot=clip_a.local_rot.copy(),
        root_pos=root_pos_b,
    )

    lag, min_dist = estimate_temporal_lag(
        clip_a, clip_b,
        overlap_range_a=(20, 50),
        overlap_range_b=(20, 50),
        max_lag=3,
    )
    # The lag detected should be +2
    assert lag == 2


def test_qc_report_json_and_html_generation(tmp_path: Path) -> None:
    """Verify MotionQCReport serializes cleanly to JSON and HTML."""
    seam_metric = SeamQCMetrics(
        seam_index=1,
        chunk_a_index=1,
        chunk_b_index=2,
        mean_angle_diff_deg=1.2,
        max_angle_diff_deg=2.8,
        yaw_correction_deg=0.5,
        translation_correction_m=0.03,
        temporal_lag=0,
        accel_spike_ratio=1.05,
        has_warning=False,
        warnings=[],
    )

    report = MotionQCReport(
        total_seams=1,
        passed_seams=1,
        total_duration_sec=30.0,
        total_frames=900,
        seams=[seam_metric],
        overall_status="clean",
    )

    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"

    report.save_json(json_path)
    report.generate_html(html_path)

    assert json_path.is_file()
    assert html_path.is_file()

    content = html_path.read_text(encoding="utf-8")
    assert "Motion Stitch Quality Report" in content
    assert "CLEAN" in content
