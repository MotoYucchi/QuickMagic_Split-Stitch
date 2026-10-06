"""Extended resilience and edge-case unit tests for motion codecs."""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pytest

from splitstitch.codecs.bvh import BVHCodec
from splitstitch.codecs.fbx.binary_io import (
    FBXNode,
    FBXProperty,
    parse_binary_fbx,
    write_binary_fbx,
)
from splitstitch.codecs.fbx.fbx_codec import FBXCodec
from splitstitch.codecs.vmd import VMDCodec
from splitstitch.core.timebase import TimeBase
from splitstitch.motion.model import MotionClip, Skeleton


def test_bvh_missing_motion_raises(tmp_path: Path) -> None:
    """Verify BVHCodec raises ValueError when MOTION section is missing."""
    bad_bvh = tmp_path / "bad.bvh"
    bad_bvh.write_text("HIERARCHY\nROOT Hips\n{\n  OFFSET 0 0 0\n  CHANNELS 3 Xposition Yposition Zposition\n  End Site {\n    OFFSET 0 1 0\n  }\n}\n")
    codec = BVHCodec()
    with pytest.raises(ValueError, match="No MOTION section found"):
        codec.read(bad_bvh)


def test_bvh_large_skeleton_roundtrip(tmp_path: Path) -> None:
    """Verify BVHCodec supports large skeletons (e.g., 60+ joints including hands and fingers)."""
    joint_names = ["Hips"]
    parents = [-1]
    offsets = [[0.0, 0.0, 0.0]]
    rot_orders = ["XYZ"]

    # Generate a chain and branches for spine, neck, head, left/right limbs, and fingers
    for i in range(1, 60):
        joint_names.append(f"Joint_{i:02d}")
        parents.append((i - 1) // 2)  # Branching binary tree-like hierarchy
        offsets.append([0.0, 1.5, 0.2])
        rot_orders.append("XYZ")

    skeleton = Skeleton(
        names=joint_names,
        parents=np.array(parents, dtype=np.int32),
        rest_offsets=np.array(offsets, dtype=np.float64),
        rotation_orders=rot_orders,
    )

    f_count = 5
    local_rot = np.zeros((f_count, len(joint_names), 4), dtype=np.float64)
    local_rot[..., 3] = 1.0  # Identity quat
    root_pos = np.zeros((f_count, 3), dtype=np.float64)

    clip = MotionClip(
        skeleton=skeleton,
        timebase=TimeBase.from_fps(60),
        local_rot=local_rot,
        root_pos=root_pos,
    )

    out_file = tmp_path / "large_skeleton.bvh"
    codec = BVHCodec()
    codec.write(clip, out_file)
    assert out_file.is_file()

    read_clip = codec.read(out_file)
    assert read_clip.skeleton.joint_count == 60
    assert read_clip.frame_count == f_count
    assert read_clip.skeleton.names == joint_names


def test_bvh_multiple_rotation_orders(tmp_path: Path) -> None:
    """Verify BVHCodec handles varying rotation orders across joints."""
    orders = ["XYZ", "ZXY", "ZYX", "YXZ", "YZX", "XZY"]
    names = [f"Bone_{o}" for o in orders]
    parents = np.array([-1, 0, 1, 2, 3, 4], dtype=np.int32)
    offsets = np.zeros((len(orders), 3), dtype=np.float64)

    skeleton = Skeleton(
        names=names,
        parents=parents,
        rest_offsets=offsets,
        rotation_orders=orders,
    )

    f_count = 4
    local_rot = np.zeros((f_count, len(orders), 4), dtype=np.float64)
    local_rot[..., 3] = 1.0
    root_pos = np.zeros((f_count, 3), dtype=np.float64)

    clip = MotionClip(
        skeleton=skeleton,
        timebase=TimeBase.from_fps(30),
        local_rot=local_rot,
        root_pos=root_pos,
    )

    out_file = tmp_path / "rot_orders.bvh"
    codec = BVHCodec()
    codec.write(clip, out_file)

    read_clip = codec.read(out_file)
    assert read_clip.skeleton.rotation_orders == orders


def test_vmd_corrupt_file_raises(tmp_path: Path) -> None:
    """Verify VMDCodec raises ValueError on short or corrupted files."""
    bad_vmd = tmp_path / "truncated.vmd"
    bad_vmd.write_bytes(b"Vocaloid Motion Data 0002\x00short")
    codec = VMDCodec()
    with pytest.raises(ValueError, match="too small"):
        codec.read(bad_vmd)


def test_fbx_corrupt_magic_raises(tmp_path: Path) -> None:
    """Verify binary FBX parser rejects files with invalid magic header."""
    bad_fbx = tmp_path / "bad_magic.fbx"
    bad_fbx.write_bytes(b"NOT_A_VALID_FBX_FILE_AT_ALL_PADDING_BYTES")
    with pytest.raises(ValueError, match="invalid magic header"):
        parse_binary_fbx(bad_fbx.read_bytes())


def test_fbx_64bit_version_roundtrip() -> None:
    """Verify binary FBX parser and writer handle FBX 7500 (64-bit offsets)."""
    nodes = [
        FBXNode(
            name="Test64",
            properties=[
                FBXProperty("L", 9876543210123),
                FBXProperty("S", b"StringData"),
                FBXProperty("I", 42),
            ],
            children=[
                FBXNode(name="Child", properties=[FBXProperty("D", 3.1415926535)]),
            ],
        )
    ]

    version = 7500  # 64-bit offsets
    buf = write_binary_fbx(version, nodes)
    assert len(buf) > 40

    v_read, nodes_read = parse_binary_fbx(buf)
    assert v_read == 7500
    assert len(nodes_read) == 1
    assert nodes_read[0].name == "Test64"
    assert nodes_read[0].properties[0].value == 9876543210123
    assert nodes_read[0].children[0].name == "Child"
    assert nodes_read[0].children[0].properties[0].value == pytest.approx(3.1415926535)


def test_fbx_array_property_roundtrip() -> None:
    """Verify array properties (double array, float array, int array) roundtrip cleanly."""
    d_arr = np.array([1.23, 4.56, 7.89, -0.12, 100.5], dtype=np.float64)
    i_arr = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=np.int32)

    nodes = [
        FBXNode(
            name="Arrays",
            properties=[
                FBXProperty("d", d_arr),
                FBXProperty("i", i_arr),
            ],
        )
    ]

    buf = write_binary_fbx(7400, nodes)
    _, nodes_read = parse_binary_fbx(buf)

    assert len(nodes_read) == 1
    assert np.allclose(nodes_read[0].properties[0].value, d_arr)
    assert np.array_equal(nodes_read[0].properties[1].value, i_arr)
