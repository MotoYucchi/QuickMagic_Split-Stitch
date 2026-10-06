"""Blending and splicing two motion clips with easing curves."""

from __future__ import annotations

import math
from typing import Tuple
import numpy as np

from splitstitch.motion.model import MotionClip
from splitstitch.motion.quat import quat_slerp
from splitstitch.motion.seam import SeamSelection


def get_easing_weights(length: int, easing: str = "smoothstep") -> np.ndarray:
    """Generate interpolation weights in [0.0, 1.0] with chosen easing curve."""
    if length <= 1:
        return np.array([0.5], dtype=np.float64)

    t = np.linspace(0.0, 1.0, length, dtype=np.float64)
    easing_lower = easing.lower()

    if easing_lower == "linear":
        return t
    elif easing_lower == "cosine":
        return 0.5 * (1.0 - np.cos(np.pi * t))
    else:  # smoothstep (Hermite interpolation)
        return t * t * (3.0 - 2.0 * t)


def blend_and_splice_clips(
    clip_a: MotionClip,
    clip_b: MotionClip,
    seam: SeamSelection,
    easing: str = "smoothstep",
) -> MotionClip:
    """Seamlessly blend clip_a and clip_b across the chosen seam window."""
    # Part 1: clip_a from 0 to seam.blend_start_a
    # Part 2: Blended transition from blend_start to blend_end
    # Part 3: clip_b from seam.blend_end_b to end of clip_b

    len_a_head = seam.blend_start_a
    window_len = seam.blend_end_a - seam.blend_start_a
    len_b_tail = clip_b.frame_count - seam.blend_end_b

    total_frames = len_a_head + window_len + len_b_tail
    J = clip_a.skeleton.joint_count

    # Allocate concatenated arrays
    merged_rot = np.zeros((total_frames, J, 4), dtype=np.float64)
    merged_root_pos = np.zeros((total_frames, 3), dtype=np.float64)

    # Copy Head from A
    merged_rot[:len_a_head] = clip_a.local_rot[:len_a_head]
    merged_root_pos[:len_a_head] = clip_a.root_pos[:len_a_head]

    # Compute Blended Window
    weights = get_easing_weights(window_len, easing=easing)  # shape (W,)
    w_col = weights[:, np.newaxis]  # shape (W, 1)

    idx_a = slice(seam.blend_start_a, seam.blend_end_a)
    idx_b = slice(seam.blend_start_b, seam.blend_end_b)
    target_idx = slice(len_a_head, len_a_head + window_len)

    # 1. Rotations via SLERP
    for j in range(J):
        q_a = clip_a.local_rot[idx_a, j, :]
        q_b = clip_b.local_rot[idx_b, j, :]
        merged_rot[target_idx, j, :] = quat_slerp(q_a, q_b, w_col)

    # 2. Root Position via Linear Blend
    pos_a = clip_a.root_pos[idx_a]
    pos_b = clip_b.root_pos[idx_b]
    merged_root_pos[target_idx] = (1.0 - w_col) * pos_a + w_col * pos_b

    # Copy Tail from B
    merged_rot[len_a_head + window_len :] = clip_b.local_rot[seam.blend_end_b :]
    merged_root_pos[len_a_head + window_len :] = clip_b.root_pos[seam.blend_end_b :]

    # Handle extra position joints
    merged_extra_pos = {}
    all_extra_keys = set(clip_a.extra_pos.keys()) | set(clip_b.extra_pos.keys())
    for j_idx in all_extra_keys:
        p_a = clip_a.extra_pos.get(j_idx, np.zeros((clip_a.frame_count, 3)))
        p_b = clip_b.extra_pos.get(j_idx, np.zeros((clip_b.frame_count, 3)))
        arr = np.zeros((total_frames, 3), dtype=np.float64)
        arr[:len_a_head] = p_a[:len_a_head]
        arr[target_idx] = (1.0 - w_col) * p_a[idx_a] + w_col * p_b[idx_b]
        arr[len_a_head + window_len :] = p_b[seam.blend_end_b :]
        merged_extra_pos[j_idx] = arr

    # Handle scalar curves (e.g. facial blendshapes)
    merged_curves = {}
    all_curve_keys = set(clip_a.curves.keys()) | set(clip_b.curves.keys())
    for c_name in all_curve_keys:
        c_a = clip_a.curves.get(c_name, np.zeros(clip_a.frame_count))
        c_b = clip_b.curves.get(c_name, np.zeros(clip_b.frame_count))
        c_arr = np.zeros(total_frames, dtype=np.float64)
        c_arr[:len_a_head] = c_a[:len_a_head]
        c_arr[target_idx] = (1.0 - weights) * c_a[idx_a] + weights * c_b[idx_b]
        c_arr[len_a_head + window_len :] = c_b[seam.blend_end_b :]
        merged_curves[c_name] = c_arr

    return MotionClip(
        skeleton=clip_a.skeleton,
        timebase=clip_a.timebase,
        local_rot=merged_rot,
        root_pos=merged_root_pos,
        extra_pos=merged_extra_pos,
        curves=merged_curves,
        codec_context=dict(clip_a.codec_context),
    )
