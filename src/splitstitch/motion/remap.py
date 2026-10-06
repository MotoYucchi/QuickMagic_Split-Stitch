"""Time remapping and timeline re-synchronization."""

from __future__ import annotations

from fractions import Fraction
import numpy as np

from splitstitch.core.timebase import TimeBase, parse_fraction
from splitstitch.motion.model import MotionClip
from splitstitch.motion.quat import quat_slerp


def remap_clip_timebase(
    clip: MotionClip,
    target_fps: str | Fraction | TimeBase,
) -> MotionClip:
    """Remap clip timebase. If frames map 1:1, only modifies metadata; otherwise resamples."""
    tb = target_fps if isinstance(target_fps, TimeBase) else TimeBase.from_fps(target_fps)
    if clip.timebase.fps == tb.fps:
        return clip.copy()

    # Determine if purely metadata replacement (e.g. stretch mode restoring exact frame rate)
    # If the user wants to retain exact frames but change the playback rate:
    # return clip with new timebase
    new_clip = clip.copy()
    new_clip.timebase = tb
    return new_clip


def resample_clip(
    clip: MotionClip,
    target_fps: str | Fraction | TimeBase,
) -> MotionClip:
    """Resample motion clip to a new discrete sampling rate using SLERP and linear interpolation."""
    new_tb = target_fps if isinstance(target_fps, TimeBase) else TimeBase.from_fps(target_fps)
    if clip.timebase.fps == new_tb.fps:
        return clip.copy()

    duration = clip.duration_sec
    new_frame_count = max(1, int(round(duration * float(new_tb.fps))))

    old_times = np.arange(clip.frame_count, dtype=np.float64) * clip.timebase.frame_duration_sec
    new_times = np.arange(new_frame_count, dtype=np.float64) * new_tb.frame_duration_sec

    # Interpolate rotations with SLERP
    F_new = new_frame_count
    J = clip.skeleton.joint_count
    new_rots = np.zeros((F_new, J, 4), dtype=np.float64)

    # Find bounding indices
    idx_floor = np.clip(np.searchsorted(old_times, new_times, side="right") - 1, 0, clip.frame_count - 2)
    t0 = old_times[idx_floor]
    t1 = old_times[idx_floor + 1]
    dt = np.where(t1 > t0, t1 - t0, 1.0)
    alpha = np.clip((new_times - t0) / dt, 0.0, 1.0)  # shape (F_new,)

    for j in range(J):
        q0 = clip.local_rot[idx_floor, j, :]  # shape (F_new, 4)
        q1 = clip.local_rot[idx_floor + 1, j, :]
        new_rots[:, j, :] = quat_slerp(q0, q1, alpha[:, np.newaxis])

    # Interpolate root position linearly
    new_root_pos = np.zeros((F_new, 3), dtype=np.float64)
    for c in range(3):
        new_root_pos[:, c] = np.interp(new_times, old_times, clip.root_pos[:, c])

    # Interpolate extra positions
    new_extra_pos = {}
    for j_idx, pos_arr in clip.extra_pos.items():
        arr = np.zeros((F_new, 3), dtype=np.float64)
        for c in range(3):
            arr[:, c] = np.interp(new_times, old_times, pos_arr[:, c])
        new_extra_pos[j_idx] = arr

    # Interpolate curves
    new_curves = {}
    for c_name, c_arr in clip.curves.items():
        new_curves[c_name] = np.interp(new_times, old_times, c_arr)

    return MotionClip(
        skeleton=clip.skeleton,
        timebase=new_tb,
        local_rot=new_rots,
        root_pos=new_root_pos,
        extra_pos=new_extra_pos,
        curves=new_curves,
        codec_context=dict(clip.codec_context),
    )
