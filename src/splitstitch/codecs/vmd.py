"""VMD (Vocaloid Motion Data) binary codec."""

from __future__ import annotations

import struct
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

from splitstitch.codecs.base import BaseCodec, CodecCapability
from splitstitch.core.timebase import TimeBase
from splitstitch.motion.model import MotionClip, Skeleton
from splitstitch.motion.remap import resample_clip


class VMDCodec(BaseCodec):
    @classmethod
    def capability(cls) -> CodecCapability:
        return CodecCapability(
            format_name="VMD",
            extensions=[".vmd"],
            can_read=True,
            can_write=True,
            is_time_based=False,  # Frame index-based (supports up to 60 FPS in MMD / MMM)
            supports_blendshapes=True,
            max_fps=60,
        )

    def read(self, path: Path | str, fps: Optional[Union[int, float, Fraction]] = None) -> MotionClip:
        p = Path(path).resolve()
        with open(p, "rb") as f:
            data = f.read()

        if len(data) < 54:
            raise ValueError(f"File too small for VMD header: {p}")

        header = data[:30].split(b"\x00")[0].decode("ascii", errors="replace")
        model_name = data[30:50].split(b"\x00")[0].decode("shift_jis", errors="replace")

        offset = 50
        (bone_key_count,) = struct.unpack_from("<I", data, offset)
        offset += 4

        bone_frames: Dict[str, Dict[int, Tuple[Tuple[float, float, float], Tuple[float, float, float, float]]]] = {}
        all_bone_names: List[str] = []
        max_frame = 0

        # Read Bone Keyframes
        # Record size = 15 (name) + 4 (frame) + 12 (pos) + 16 (rot) + 64 (interp) = 111 bytes
        for _ in range(bone_key_count):
            if offset + 111 > len(data):
                break
            raw_name = data[offset : offset + 15].split(b"\x00")[0]
            name = raw_name.decode("shift_jis", errors="replace")
            frame_idx, px, py, pz, qx, qy, qz, qw = struct.unpack_from("<I7f", data, offset + 15)
            offset += 111

            if name not in bone_frames:
                bone_frames[name] = {}
                all_bone_names.append(name)
            bone_frames[name][frame_idx] = ((px, py, pz), (qx, qy, qz, qw))
            if frame_idx > max_frame:
                max_frame = frame_idx

        # Read Morph Keyframes
        morph_curves: Dict[str, np.ndarray] = {}
        if offset + 4 <= len(data):
            (morph_count,) = struct.unpack_from("<I", data, offset)
            offset += 4
            # Morph record = 15 (name) + 4 (frame) + 4 (weight) = 23 bytes
            morph_data: Dict[str, Dict[int, float]] = {}
            for _ in range(morph_count):
                if offset + 23 > len(data):
                    break
                raw_mname = data[offset : offset + 15].split(b"\x00")[0]
                mname = raw_mname.decode("shift_jis", errors="replace")
                m_frame, weight = struct.unpack_from("<If", data, offset + 15)
                offset += 23
                if mname not in morph_data:
                    morph_data[mname] = {}
                morph_data[mname][m_frame] = weight

            total_f = max_frame + 1
            for mname, f_dict in morph_data.items():
                curve_arr = np.zeros(total_f, dtype=np.float64)
                sorted_f = sorted(f_dict.keys())
                for f_num in sorted_f:
                    curve_arr[f_num] = f_dict[f_num]
                morph_curves[mname] = curve_arr

        total_frames = max(1, max_frame + 1)
        J = len(all_bone_names)
        local_rot = np.zeros((total_frames, J, 4), dtype=np.float64)
        local_rot[..., 3] = 1.0  # Identity quat
        root_pos = np.zeros((total_frames, 3), dtype=np.float64)

        root_idx = 0
        for j, bname in enumerate(all_bone_names):
            if bname in ("全ての親", "センター", "グルーブ", "root", "hips"):
                root_idx = j
            b_dict = bone_frames[bname]
            for f_idx, (pos, rot) in b_dict.items():
                if f_idx < total_frames:
                    local_rot[f_idx, j, :] = rot
                    if j == root_idx:
                        root_pos[f_idx, :] = pos

        skeleton = Skeleton(
            names=all_bone_names,
            parents=np.full(J, -1, dtype=np.int32),
            rest_offsets=np.zeros((J, 3), dtype=np.float64),
            root_index=root_idx,
        )

        timebase = TimeBase.from_fps(Fraction(fps) if fps is not None else 30)
        return MotionClip(
            skeleton=skeleton,
            timebase=timebase,
            local_rot=local_rot,
            root_pos=root_pos,
            curves=morph_curves,
            codec_context={"model_name": model_name},
        )

    def write(self, clip: MotionClip, output_path: Path | str, template_path: Optional[Path | str] = None) -> None:
        p = Path(output_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)

        # VMD supports up to 60fps in official MMD and compatible tools (such as MikuMikuMoving).
        # Clips up to 60fps (24, 30, 60fps) are preserved directly.
        # Clips exceeding 60fps (e.g. 120fps) are automatically resampled to 60fps.
        fps_float = float(clip.timebase.fps)
        if fps_float > 60.0 + 1e-4:
            target_clip = resample_clip(clip, 60)
        elif abs(fps_float - 59.94) < 0.1:
            target_clip = resample_clip(clip, 60)
        else:
            target_clip = clip

        header_bytes = b"Vocaloid Motion Data 0002\x00\x00\x00\x00\x00"
        model_name = target_clip.codec_context.get("model_name", "QuickMagic")
        model_bytes = model_name.encode("shift_jis", errors="replace")[:20].ljust(20, b"\x00")

        total_frames = target_clip.frame_count
        J = target_clip.skeleton.joint_count

        # Build bone keyframes: write all frames
        bone_records = []
        default_interp = b"\x14\x14\x14\x14" * 16  # standard linear interpolation curve

        for j in range(J):
            bname = target_clip.skeleton.names[j]
            name_bytes = bname.encode("shift_jis", errors="replace")[:15].ljust(15, b"\x00")
            is_root = (j == target_clip.skeleton.root_index)

            for f in range(total_frames):
                pos = target_clip.root_pos[f] if is_root else (0.0, 0.0, 0.0)
                rot = target_clip.local_rot[f, j]
                rec = (
                    name_bytes
                    + struct.pack("<I7f", f, pos[0], pos[1], pos[2], rot[0], rot[1], rot[2], rot[3])
                    + default_interp
                )
                bone_records.append(rec)

        # Build morph keyframes
        morph_records = []
        for mname, curve_arr in target_clip.curves.items():
            mname_bytes = mname.encode("shift_jis", errors="replace")[:15].ljust(15, b"\x00")
            for f in range(min(total_frames, len(curve_arr))):
                val = float(curve_arr[f])
                if abs(val) > 1e-4:  # Only output non-zero morph keys to save size
                    morph_records.append(mname_bytes + struct.pack("<If", f, val))

        with open(p, "wb") as f:
            f.write(header_bytes)
            f.write(model_bytes)
            # Bone key count
            f.write(struct.pack("<I", len(bone_records)))
            for r in bone_records:
                f.write(r)
            # Morph key count
            f.write(struct.pack("<I", len(morph_records)))
            for mr in morph_records:
                f.write(mr)
            # Camera key count (0)
            f.write(struct.pack("<I", 0))
            # Light key count (0)
            f.write(struct.pack("<I", 0))
            # Shadow key count (0)
            f.write(struct.pack("<I", 0))
            # IK key count (0)
            f.write(struct.pack("<I", 0))
