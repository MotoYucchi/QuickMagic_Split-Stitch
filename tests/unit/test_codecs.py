"""Unit tests for motion codecs (BVH, VMD, and binary FBX)."""

from pathlib import Path
import numpy as np
import pytest

from splitstitch.codecs.bvh import BVHCodec
from splitstitch.codecs.fbx.binary_io import parse_binary_fbx, write_binary_fbx, FBXNode, FBXProperty
from splitstitch.codecs.fbx.fbx_codec import FBXCodec
from splitstitch.codecs.vmd import VMDCodec
from splitstitch.core.timebase import TimeBase
from splitstitch.motion.model import MotionClip, Skeleton


def test_bvh_roundtrip(tmp_path: Path) -> None:
    # Build synthetic MotionClip
    names = ["Hips", "Spine", "Head"]
    parents = np.array([-1, 0, 1], dtype=np.int32)
    offsets = np.array([[0, 0, 0], [0, 10, 0], [0, 20, 0]], dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, rotation_orders=["XYZ", "XYZ", "XYZ"])

    F = 10
    timebase = TimeBase.from_fps(30)
    local_rot = np.zeros((F, 3, 4), dtype=np.float64)
    local_rot[..., 3] = 1.0  # identity quat
    root_pos = np.zeros((F, 3), dtype=np.float64)
    for f in range(F):
        root_pos[f, :] = [f * 0.1, 1.0, f * 0.2]

    clip = MotionClip(skeleton=skeleton, timebase=timebase, local_rot=local_rot, root_pos=root_pos)

    bvh_file = tmp_path / "test.bvh"
    codec = BVHCodec()
    codec.write(clip, bvh_file)

    assert bvh_file.is_file()

    # Read back
    read_clip = codec.read(bvh_file)
    assert read_clip.frame_count == F
    assert read_clip.skeleton.joint_count == 3
    assert np.allclose(read_clip.root_pos, root_pos, atol=1e-4)


def test_vmd_roundtrip(tmp_path: Path) -> None:
    names = ["全ての親", "センター", "頭"]
    parents = np.array([-1, 0, 1], dtype=np.int32)
    offsets = np.zeros((3, 3), dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, root_index=0)

    F = 15
    timebase = TimeBase.from_fps(30)
    local_rot = np.zeros((F, 3, 4), dtype=np.float64)
    local_rot[..., 3] = 1.0
    root_pos = np.zeros((F, 3), dtype=np.float64)
    root_pos[:, 1] = 10.0

    curves = {"笑い": np.full(F, 0.8, dtype=np.float64)}

    clip = MotionClip(skeleton=skeleton, timebase=timebase, local_rot=local_rot, root_pos=root_pos, curves=curves)

    vmd_file = tmp_path / "test.vmd"
    codec = VMDCodec()
    codec.write(clip, vmd_file)

    assert vmd_file.is_file()

    read_clip = codec.read(vmd_file)
    assert read_clip.frame_count == F
    assert "笑い" in read_clip.curves
    assert read_clip.curves["笑い"][0] == pytest.approx(0.8, abs=1e-3)


def test_vmd_60fps_preservation(tmp_path: Path) -> None:
    """Verify VMDCodec preserves 60fps data without downsampling to 30fps."""
    names = ["全ての親", "センター"]
    parents = np.array([-1, 0], dtype=np.int32)
    offsets = np.zeros((2, 3), dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, root_index=0)

    F = 60  # 1 second of 60fps
    timebase = TimeBase.from_fps(60)
    local_rot = np.zeros((F, 2, 4), dtype=np.float64)
    local_rot[..., 3] = 1.0
    root_pos = np.zeros((F, 3), dtype=np.float64)

    clip = MotionClip(skeleton=skeleton, timebase=timebase, local_rot=local_rot, root_pos=root_pos)

    vmd_file = tmp_path / "test_60fps.vmd"
    codec = VMDCodec()
    codec.write(clip, vmd_file)

    # Read back at 60fps
    read_clip = codec.read(vmd_file, fps=60)
    assert read_clip.frame_count == 60
    assert float(read_clip.timebase.fps) == 60.0
    assert read_clip.duration_sec == pytest.approx(1.0)


def test_vmd_120fps_resampled_to_60fps(tmp_path: Path) -> None:
    """Verify VMDCodec resamples 120fps data to the 60fps upper limit."""
    names = ["全ての親", "センター"]
    parents = np.array([-1, 0], dtype=np.int32)
    offsets = np.zeros((2, 3), dtype=np.float64)
    skeleton = Skeleton(names=names, parents=parents, rest_offsets=offsets, root_index=0)

    F = 120  # 1 second of 120fps
    timebase = TimeBase.from_fps(120)
    local_rot = np.zeros((F, 2, 4), dtype=np.float64)
    local_rot[..., 3] = 1.0
    root_pos = np.zeros((F, 3), dtype=np.float64)

    clip = MotionClip(skeleton=skeleton, timebase=timebase, local_rot=local_rot, root_pos=root_pos)

    vmd_file = tmp_path / "test_120fps.vmd"
    codec = VMDCodec()
    codec.write(clip, vmd_file)

    # When read back at 60fps, exactly 60 frames should be present
    read_clip = codec.read(vmd_file, fps=60)
    assert read_clip.frame_count == 60
    assert read_clip.duration_sec == pytest.approx(1.0)



def test_binary_fbx_io() -> None:
    # Test low-level binary FBX parser and serializer
    nodes = [
        FBXNode(
            name="GlobalSettings",
            properties=[FBXProperty("I", 7400)],
            children=[
                FBXNode(name="Properties70", properties=[FBXProperty("S", b"UnitScaleFactor")]),
            ],
        ),
        FBXNode(
            name="Objects",
            properties=[],
            children=[
                FBXNode(
                    name="Model",
                    properties=[FBXProperty("L", 12345), FBXProperty("S", b"Model::Hips\x00\x01Model")],
                )
            ],
        ),
    ]

    version = 7400
    serialized = write_binary_fbx(version, nodes)
    assert len(serialized) > 50

    v_read, nodes_read = parse_binary_fbx(serialized)
    assert v_read == version
    assert len(nodes_read) == 2
    assert nodes_read[0].name == "GlobalSettings"
    assert nodes_read[1].name == "Objects"
    assert len(nodes_read[1].children) == 1
    assert nodes_read[1].children[0].properties[0].value == 12345
