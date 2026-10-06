"""Quaternion mathematics: SLERP, hemisphere alignment, and Euler unwrap."""

from __future__ import annotations

import math
import numpy as np
from scipy.spatial.transform import Rotation


def normalize_quats(q: np.ndarray) -> np.ndarray:
    """Normalize quaternions (x, y, z, w). Supports any leading dimensions."""
    norm = np.linalg.norm(q, axis=-1, keepdims=True)
    norm = np.where(norm < 1e-12, 1.0, norm)
    return q / norm


def align_hemisphere(q_ref: np.ndarray, q_target: np.ndarray) -> np.ndarray:
    """Ensure q_target is in the same hemisphere as q_ref (dot product >= 0)."""
    dots = np.sum(q_ref * q_target, axis=-1, keepdims=True)
    return np.where(dots < 0.0, -q_target, q_target)


def quat_slerp(q0: np.ndarray, q1: np.ndarray, t: float | np.ndarray) -> np.ndarray:
    """Spherical linear interpolation between two quaternions (x, y, z, w)."""
    q0 = normalize_quats(q0)
    q1 = normalize_quats(q1)
    q1 = align_hemisphere(q0, q1)

    dot = np.sum(q0 * q1, axis=-1, keepdims=True)
    dot = np.clip(dot, -1.0, 1.0)

    theta = np.arccos(dot)
    sin_theta = np.sin(theta)

    # For tiny angles, fallback to normalized linear interpolation
    is_linear = np.abs(sin_theta) < 1e-6

    scale0 = np.where(is_linear, 1.0 - t, np.sin((1.0 - t) * theta) / (sin_theta + 1e-12))
    scale1 = np.where(is_linear, t, np.sin(t * theta) / (sin_theta + 1e-12))

    res = scale0 * q0 + scale1 * q1
    return normalize_quats(res)


def quat_angle_diff(q0: np.ndarray, q1: np.ndarray) -> np.ndarray:
    """Calculate absolute angular difference in radians between two quaternions."""
    q0 = normalize_quats(q0)
    q1 = normalize_quats(q1)
    dot = np.abs(np.sum(q0 * q1, axis=-1))
    dot = np.clip(dot, -1.0, 1.0)
    return 2.0 * np.arccos(dot)


def extract_yaw_radians(q: np.ndarray) -> float:
    """Extract yaw angle around Y axis from quaternion (x, y, z, w)."""
    x, y, z, w = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    # Y-up yaw: atan2(2*(w*y + x*z), 1 - 2*(y^2 + z^2))
    siny_cosp = 2.0 * (w * y + x * z)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def make_yaw_quat(yaw_rad: float) -> np.ndarray:
    """Create quaternion (x, y, z, w) representing rotation around Y axis."""
    half = yaw_rad * 0.5
    return np.array([0.0, math.sin(half), 0.0, math.cos(half)], dtype=np.float64)


def quat_multiply(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Multiply two quaternions: q_res = q1 * q2."""
    x1, y1, z1, w1 = q1[..., 0], q1[..., 1], q1[..., 2], q1[..., 3]
    x2, y2, z2, w2 = q2[..., 0], q2[..., 1], q2[..., 2], q2[..., 3]
    return np.stack([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ], axis=-1)


def unwrap_euler(angles_deg: np.ndarray) -> np.ndarray:
    """Unwrap Euler angles (shape (F, ...)) to prevent 360-degree jumps across frames."""
    unwrapped = np.empty_like(angles_deg)
    unwrapped[0] = angles_deg[0]
    for i in range(1, len(angles_deg)):
        diff = angles_deg[i] - angles_deg[i - 1]
        diff = (diff + 180.0) % 360.0 - 180.0
        unwrapped[i] = unwrapped[i - 1] + diff
    return unwrapped
