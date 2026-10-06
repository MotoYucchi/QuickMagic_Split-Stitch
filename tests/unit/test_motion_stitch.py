"""Unit tests for motion stitching, alignment, and blending."""

import math
from fractions import Fraction
from pathlib import Path
import numpy as np
import pytest

from splitstitch.core.timebase import TimeBase
from splitstitch.motion.align import align_adjacent_clips
from splitstitch.motion.blend import blend_and_splice_clips
from splitstitch.motion.model import MotionClip, Skeleton
from splitstitch.motion.quat import extract_yaw_radians, make_yaw_quat
from splitstitch.motion.seam import find_optimal_seam


def create_synthetic_clip(frame_count: int, yaw_deg: float = 0.0, offset_x: float = 0.0) -> MotionClip:
    names = ["Hips", "Spine"]
    parents = np.array([-1, 0], dtype=np.int32)
    offsets = np.array([[0, 0, 0], [0, 1, 0]], dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, root_index=0)

    timebase = TimeBase.from_fps(30)
    local_rot = np.zeros((frame_count, 2, 4), dtype=np.float64)
    local_rot[..., 3] = 1.0  # identity

    # Apply root yaw
    q_yaw = make_yaw_quat(math.radians(yaw_deg))
    for f in range(frame_count):
        local_rot[f, 0, :] = q_yaw

    root_pos = np.zeros((frame_count, 3), dtype=np.float64)
    for f in range(frame_count):
        root_pos[f, :] = [offset_x + f * 0.05, 1.0, 0.0]

    return MotionClip(skeleton=skeleton, timebase=timebase, local_rot=local_rot, root_pos=root_pos)


def test_rigid_alignment() -> None:
    # Clip A: 60 frames, no rotation, pos starts at 0
    clip_a = create_synthetic_clip(60, yaw_deg=0.0, offset_x=0.0)

    # Clip B represents subsequent 60 frames with 30-frame overlap.
    # In overlap (frames 30-60 of A), Clip A root_pos.x is from 1.5 to 3.0.
    # If Clip B has a drift offset (e.g. starts at 0.0 instead of 1.5) and 10 deg yaw rotation:
    clip_b = create_synthetic_clip(60, yaw_deg=10.0, offset_x=0.0)

    # Overlap ranges: A[30:60], B[0:30]
    align_res = align_adjacent_clips(
        clip_a=clip_a,
        clip_b=clip_b,
        overlap_range_a=(30, 60),
        overlap_range_b=(0, 30),
        align_mode="yaw+xz",
    )

    # Yaw correction should be around -10 degrees
    assert align_res.yaw_deg == pytest.approx(-10.0, abs=0.5)

    # Aligned clip B root orientation should match clip A (0 deg yaw)
    q_b_root = align_res.aligned_clip.local_rot[0, 0, :]
    assert extract_yaw_radians(q_b_root) == pytest.approx(0.0, abs=1e-3)

    # Aligned clip B start position should align with clip A at frame 30 (1.5)
    assert align_res.aligned_clip.root_pos[0, 0] == pytest.approx(1.5, abs=0.1)


def test_seam_and_blend() -> None:
    clip_a = create_synthetic_clip(50)
    clip_b = create_synthetic_clip(50, offset_x=2.0)

    seam = find_optimal_seam(
        clip_a=clip_a,
        clip_b=clip_b,
        overlap_range_a=(30, 50),
        overlap_range_b=(0, 20),
        blend_frames=10,
        guard_frames=2,
    )

    assert seam.blend_start_a >= 30
    assert seam.blend_end_a <= 50

    merged = blend_and_splice_clips(
        clip_a=clip_a,
        clip_b=clip_b,
        seam=seam,
        easing="smoothstep",
    )

    # Check total frame count is seamless
    expected_frames = seam.blend_start_a + (seam.blend_end_a - seam.blend_start_a) + (50 - seam.blend_end_b)
    assert merged.frame_count == expected_frames
