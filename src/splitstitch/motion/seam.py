"""Optimal seam point selection and lag detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np

from splitstitch.motion.model import MotionClip
from splitstitch.motion.quat import quat_angle_diff


def compute_pose_distance(
    clip_a: MotionClip,
    clip_b: MotionClip,
    indices_a: np.ndarray,
    indices_b: np.ndarray,
    joint_weights: Optional[np.ndarray] = None,
    pos_weight: float = 0.5,
) -> np.ndarray:
    """Compute per-frame distance between poses of clip_a and clip_b."""
    # Rotation distance
    # clip.local_rot: shape (F, J, 4)
    q_a = clip_a.local_rot[indices_a]  # (K, J, 4)
    q_b = clip_b.local_rot[indices_b]  # (K, J, 4)

    ang_diff = quat_angle_diff(q_a, q_b)  # (K, J) in radians

    if joint_weights is None:
        # Default weights: root, hips, spine higher weight
        J = clip_a.skeleton.joint_count
        weights = np.ones(J, dtype=np.float64)
        if J > 0:
            weights[0] = 3.0  # Root
        if J > 5:
            weights[1:6] = 2.0  # Spine / Hips
        weights /= np.sum(weights)
    else:
        weights = joint_weights / np.sum(joint_weights)

    rot_dist = np.sum(ang_diff * weights, axis=-1)  # (K,)

    # Position distance of root
    pos_a = clip_a.root_pos[indices_a]
    pos_b = clip_b.root_pos[indices_b]
    pos_dist = np.linalg.norm(pos_a - pos_b, axis=-1)  # (K,) in meters

    return rot_dist + pos_weight * pos_dist


def estimate_temporal_lag(
    clip_a: MotionClip,
    clip_b: MotionClip,
    overlap_range_a: Tuple[int, int],
    overlap_range_b: Tuple[int, int],
    max_lag: int = 3,
) -> Tuple[int, float]:
    """Search for temporal frame lag in [-max_lag, max_lag] minimizing pose distance."""
    start_a, end_a = overlap_range_a
    start_b, end_b = overlap_range_b

    len_a = end_a - start_a
    len_b = end_b - start_b
    common_len = min(len_a, len_b)

    if common_len <= 2 * max_lag + 2:
        return 0, 0.0

    best_lag = 0
    min_dist = float("inf")

    for lag in range(-max_lag, max_lag + 1):
        # Clip B shifted by lag relative to A
        sub_len = common_len - 2 * max_lag
        idx_a = np.arange(start_a + max_lag, start_a + max_lag + sub_len)
        idx_b = np.arange(start_b + max_lag + lag, start_b + max_lag + lag + sub_len)

        dists = compute_pose_distance(clip_a, clip_b, idx_a, idx_b)
        mean_d = float(np.mean(dists))

        if mean_d < min_dist:
            min_dist = mean_d
            best_lag = lag

    return best_lag, min_dist


@dataclass
class SeamSelection:
    optimal_center_a: int
    optimal_center_b: int
    blend_start_a: int
    blend_end_a: int
    blend_start_b: int
    blend_end_b: int
    mean_error: float


def find_optimal_seam(
    clip_a: MotionClip,
    clip_b: MotionClip,
    overlap_range_a: Tuple[int, int],
    overlap_range_b: Tuple[int, int],
    blend_frames: int,
    guard_frames: int = 8,
    seam_mode: str = "auto",  # "auto" or "center"
) -> SeamSelection:
    """Find the seam location with minimal pose discontinuity within the overlap region."""
    start_a, end_a = overlap_range_a
    start_b, end_b = overlap_range_b

    eval_len = min(end_a - start_a, end_b - start_b)
    half_blend = max(1, blend_frames // 2)

    # Core region excluding guard frames at edges
    core_start = guard_frames
    core_end = eval_len - guard_frames

    if core_end <= core_start + blend_frames or seam_mode == "center":
        # Fallback to direct center
        center_rel = eval_len // 2
        center_a = start_a + center_rel
        center_b = start_b + center_rel
        return SeamSelection(
            optimal_center_a=center_a,
            optimal_center_b=center_b,
            blend_start_a=center_a - half_blend,
            blend_end_a=center_a + half_blend,
            blend_start_b=center_b - half_blend,
            blend_end_b=center_b + half_blend,
            mean_error=0.0,
        )

    # Search window centers in [core_start + half_blend, core_end - half_blend]
    valid_centers = np.arange(core_start + half_blend, core_end - half_blend)
    idx_a = start_a + np.arange(eval_len)
    idx_b = start_b + np.arange(eval_len)
    per_frame_dist = compute_pose_distance(clip_a, clip_b, idx_a, idx_b)

    best_center_rel = valid_centers[0]
    min_window_dist = float("inf")

    for c in valid_centers:
        w_dist = float(np.mean(per_frame_dist[c - half_blend : c + half_blend]))
        if w_dist < min_window_dist:
            min_window_dist = w_dist
            best_center_rel = c

    center_a = start_a + best_center_rel
    center_b = start_b + best_center_rel

    return SeamSelection(
        optimal_center_a=center_a,
        optimal_center_b=center_b,
        blend_start_a=center_a - half_blend,
        blend_end_a=center_a + half_blend,
        blend_start_b=center_b - half_blend,
        blend_end_b=center_b + half_blend,
        mean_error=round(min_window_dist, 4),
    )
