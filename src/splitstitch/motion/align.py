"""Rigid body alignment (Yaw rotation + horizontal translation offset)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple
import numpy as np

from splitstitch.motion.model import MotionClip
from splitstitch.motion.quat import (
    extract_yaw_radians,
    make_yaw_quat,
    normalize_quats,
    quat_multiply,
)


@dataclass
class AlignResult:
    yaw_deg: float
    offset_xyz: np.ndarray  # shape (3,)
    aligned_clip: MotionClip


def rotate_vector_by_yaw(vec: np.ndarray, yaw_rad: float) -> np.ndarray:
    """Rotate 3D vectors around Y axis by yaw_rad. Supports shape (..., 3)."""
    cos_y = math.cos(yaw_rad)
    sin_y = math.sin(yaw_rad)
    x = vec[..., 0]
    y = vec[..., 1]
    z = vec[..., 2]

    x_new = cos_y * x + sin_y * z
    z_new = -sin_y * x + cos_y * z
    return np.stack([x_new, y, z_new], axis=-1)


def align_adjacent_clips(
    clip_a: MotionClip,
    clip_b: MotionClip,
    overlap_range_a: Tuple[int, int],  # [start, end) indices in clip_a
    overlap_range_b: Tuple[int, int],  # [start, end) indices in clip_b
    align_mode: str = "yaw+xz",  # "yaw+xz", "xz", "none"
    vertical_mode: str = "keep",  # "keep" or "align"
) -> AlignResult:
    """Align clip_b onto clip_a coordinate space using overlapping corresponding frames."""
    start_a, end_a = overlap_range_a
    start_b, end_b = overlap_range_b

    len_a = end_a - start_a
    len_b = end_b - start_b
    eval_len = min(len_a, len_b)

    if eval_len <= 0 or align_mode == "none":
        return AlignResult(
            yaw_deg=0.0,
            offset_xyz=np.zeros(3, dtype=np.float64),
            aligned_clip=clip_b.copy(),
        )

    # 1. Yaw angle alignment via circular mean of yaw difference
    root_idx = clip_a.skeleton.root_index
    q_a = clip_a.local_rot[start_a : start_a + eval_len, root_idx, :]
    q_b = clip_b.local_rot[start_b : start_b + eval_len, root_idx, :]

    if "yaw" in align_mode:
        yaw_diffs = []
        for i in range(eval_len):
            yaw_a = extract_yaw_radians(q_a[i])
            yaw_b = extract_yaw_radians(q_b[i])
            yaw_diffs.append(yaw_a - yaw_b)

        # Circular mean of angles
        sin_sum = sum(math.sin(d) for d in yaw_diffs)
        cos_sum = sum(math.cos(d) for d in yaw_diffs)
        mean_yaw_rad = math.atan2(sin_sum, cos_sum)
    else:
        mean_yaw_rad = 0.0

    # 2. Position offset
    pos_a = clip_a.root_pos[start_a : start_a + eval_len]
    pos_b = clip_b.root_pos[start_b : start_b + eval_len]

    # Rotate pos_b by mean_yaw_rad first
    pos_b_rot = rotate_vector_by_yaw(pos_b, mean_yaw_rad)

    diff = pos_a - pos_b_rot  # shape (eval_len, 3)
    mean_offset = np.mean(diff, axis=0)

    if vertical_mode == "keep":
        mean_offset[1] = 0.0  # Preserve original Y (ground estimation)

    if align_mode == "none":
        mean_offset[:] = 0.0

    # 3. Apply transformation to the entire clip_b
    b_new = clip_b.copy()

    # Rotate root orientation by yaw quaternion
    if abs(mean_yaw_rad) > 1e-6:
        q_yaw = make_yaw_quat(mean_yaw_rad)
        # Multiply yaw rotation in world/parent space: q_res = q_yaw * q_b
        # Expand q_yaw to match b_new frames
        q_yaw_expanded = np.tile(q_yaw, (b_new.frame_count, 1))
        b_new.local_rot[:, root_idx, :] = normalize_quats(
            quat_multiply(q_yaw_expanded, b_new.local_rot[:, root_idx, :])
        )

    # Rotate and translate root position
    b_new.root_pos = rotate_vector_by_yaw(b_new.root_pos, mean_yaw_rad) + mean_offset

    # Also transform any extra position joints
    for j_idx in b_new.extra_pos:
        b_new.extra_pos[j_idx] = (
            rotate_vector_by_yaw(b_new.extra_pos[j_idx], mean_yaw_rad) + mean_offset
        )

    return AlignResult(
        yaw_deg=round(math.degrees(mean_yaw_rad), 3),
        offset_xyz=mean_offset,
        aligned_clip=b_new,
    )
