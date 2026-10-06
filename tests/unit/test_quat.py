"""Unit tests for quaternion operations."""

import math
import numpy as np
import pytest

from splitstitch.motion.quat import (
    align_hemisphere,
    extract_yaw_radians,
    make_yaw_quat,
    normalize_quats,
    quat_angle_diff,
    quat_multiply,
    quat_slerp,
    unwrap_euler,
)


def test_normalize_and_hemisphere() -> None:
    q = np.array([1.0, 2.0, 3.0, 4.0])
    q_norm = normalize_quats(q)
    assert np.linalg.norm(q_norm) == pytest.approx(1.0)

    q_opp = -q_norm
    q_aligned = align_hemisphere(q_norm, q_opp)
    assert np.allclose(q_aligned, q_norm)


def test_quat_slerp() -> None:
    # 90 degrees around Y axis
    # q0: identity
    q0 = np.array([0.0, 0.0, 0.0, 1.0])
    # q1: 90 deg around Y -> sin(45)=0.7071, cos(45)=0.7071
    q1 = make_yaw_quat(math.pi / 2.0)

    # Midway at t=0.5 -> 45 deg around Y
    q_mid = quat_slerp(q0, q1, 0.5)
    yaw_mid = extract_yaw_radians(q_mid)
    assert yaw_mid == pytest.approx(math.pi / 4.0, abs=1e-4)

    # Difference
    diff = quat_angle_diff(q0, q1)
    assert diff == pytest.approx(math.pi / 2.0, abs=1e-4)


def test_yaw_extraction_and_multiplication() -> None:
    yaw_45 = math.radians(45.0)
    q_yaw = make_yaw_quat(yaw_45)
    extracted = extract_yaw_radians(q_yaw)
    assert extracted == pytest.approx(yaw_45, abs=1e-5)

    # Double rotation: 45 + 45 = 90
    q_double = quat_multiply(q_yaw, q_yaw)
    extracted_double = extract_yaw_radians(q_double)
    assert extracted_double == pytest.approx(math.radians(90.0), abs=1e-5)


def test_unwrap_euler() -> None:
    # Series of angles wrapping around 360
    angles = np.array([350.0, 355.0, 5.0, 15.0])
    unwrapped = unwrap_euler(angles)
    assert unwrapped[2] == pytest.approx(365.0)
    assert unwrapped[3] == pytest.approx(375.0)
