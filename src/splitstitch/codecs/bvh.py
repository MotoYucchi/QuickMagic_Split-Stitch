"""BVH (Biovision Hierarchy) motion codec."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path
from typing import Any, List, Optional, Tuple
import numpy as np
from scipy.spatial.transform import Rotation

from splitstitch.codecs.base import BaseCodec, CodecCapability
from splitstitch.core.timebase import TimeBase
from splitstitch.motion.model import MotionClip, Skeleton
from splitstitch.motion.quat import unwrap_euler


class BVHCodec(BaseCodec):
    @classmethod
    def capability(cls) -> CodecCapability:
        return CodecCapability(
            format_name="BVH",
            extensions=[".bvh"],
            can_read=True,
            can_write=True,
            is_time_based=True,
            supports_blendshapes=False,
        )

    def read(self, path: Path | str) -> MotionClip:
        p = Path(path).resolve()
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]

        # Parse HIERARCHY
        joint_names: List[str] = []
        parents: List[int] = []
        offsets: List[List[float]] = []
        channels_list: List[List[str]] = []
        rot_orders: List[str] = []

        hierarchy_text_lines = []
        motion_idx = -1
        for idx, line in enumerate(lines):
            if line.startswith("MOTION"):
                motion_idx = idx
                break
            hierarchy_text_lines.append(line)

        if motion_idx == -1:
            raise ValueError(f"No MOTION section found in {p}")

        # Parse hierarchy tree
        stack: List[int] = []
        current_joint = -1

        for line in hierarchy_text_lines:
            tokens = line.split()
            token = tokens[0].upper()
            if token in ("ROOT", "JOINT"):
                name = tokens[1]
                joint_idx = len(joint_names)
                joint_names.append(name)
                parent_idx = stack[-1] if stack else -1
                parents.append(parent_idx)
                offsets.append([0.0, 0.0, 0.0])
                channels_list.append([])
                rot_orders.append("XYZ")
                current_joint = joint_idx
            elif token == "OFFSET":
                if current_joint >= 0 and current_joint < len(offsets):
                    offsets[current_joint] = [float(tokens[1]), float(tokens[2]), float(tokens[3])]
            elif token == "CHANNELS":
                if current_joint >= 0 and current_joint < len(channels_list):
                    num = int(tokens[1])
                    chans = [t.upper() for t in tokens[2 : 2 + num]]
                    channels_list[current_joint] = chans
                    # Extract rotation order (e.g. Zrotation, Xrotation, Yrotation -> ZXY)
                    rot_tokens = [c[0] for c in chans if c.endswith("ROTATION")]
                    if len(rot_tokens) == 3:
                        rot_orders[current_joint] = "".join(rot_tokens)
            elif token == "{":
                if current_joint >= 0:
                    stack.append(current_joint)
            elif token == "}":
                if stack:
                    stack.pop()

        # Parse MOTION header
        frames_line = lines[motion_idx + 1]
        frame_time_line = lines[motion_idx + 2]

        m_frames = re.search(r"Frames:\s*(\d+)", frames_line, re.IGNORECASE)
        num_frames = int(m_frames.group(1)) if m_frames else 0

        m_ft = re.search(r"Frame Time:\s*([0-9.]+)", frame_time_line, re.IGNORECASE)
        frame_time_sec = float(m_ft.group(1)) if m_ft else 0.033333

        raw_fps = 1.0 / frame_time_sec if frame_time_sec > 0 else 30.0
        # Snap to standard rational FPS if within 0.1% tolerance
        standard_candidates = [
            Fraction(24, 1), Fraction(24000, 1001),
            Fraction(25, 1),
            Fraction(30, 1), Fraction(30000, 1001),
            Fraction(50, 1),
            Fraction(60, 1), Fraction(60000, 1001),
            Fraction(120, 1), Fraction(240, 1),
        ]
        fps = Fraction(raw_fps).limit_denominator(120000)
        for cand in standard_candidates:
            if abs(float(cand) - raw_fps) / float(cand) < 0.001:
                fps = cand
                break

        timebase = TimeBase.from_fps(fps)

        # Parse Motion Data values
        motion_data_lines = lines[motion_idx + 3 :]
        data_vals: List[float] = []
        for dline in motion_data_lines:
            data_vals.extend(float(v) for v in dline.split())

        # Determine total channel count
        total_channels = sum(len(c) for c in channels_list)
        if total_channels == 0:
            raise ValueError(f"No channels defined in BVH hierarchy of {p}")

        actual_frames = len(data_vals) // total_channels
        raw_arr = np.array(data_vals[: actual_frames * total_channels], dtype=np.float64).reshape(
            (actual_frames, total_channels)
        )

        J = len(joint_names)
        local_rot = np.zeros((actual_frames, J, 4), dtype=np.float64)
        local_rot[..., 3] = 1.0  # identity quaternion
        root_pos = np.zeros((actual_frames, 3), dtype=np.float64)
        extra_pos = {}

        col_cursor = 0
        for j in range(J):
            chans = channels_list[j]
            ch_count = len(chans)
            if ch_count == 0:
                continue

            j_vals = raw_arr[:, col_cursor : col_cursor + ch_count]
            col_cursor += ch_count

            # Extract translation
            pos_indices = [idx for idx, c in enumerate(chans) if c.endswith("POSITION")]
            if len(pos_indices) == 3:
                # Typically Xposition, Yposition, Zposition
                pos_data = j_vals[:, pos_indices]
                if j == 0:
                    root_pos = pos_data
                else:
                    extra_pos[j] = pos_data

            # Extract rotation
            rot_indices = [idx for idx, c in enumerate(chans) if c.endswith("ROTATION")]
            if len(rot_indices) == 3:
                rot_angles = j_vals[:, rot_indices]  # in degrees
                order = rot_orders[j]
                r = Rotation.from_euler(order.lower(), rot_angles, degrees=True)
                local_rot[:, j, :] = r.as_quat()  # (x, y, z, w)

        skeleton = Skeleton(
            names=joint_names,
            parents=np.array(parents, dtype=np.int32),
            rest_offsets=np.array(offsets, dtype=np.float64),
            rotation_orders=rot_orders,
            root_index=0,
        )

        context = {
            "channels_list": channels_list,
            "hierarchy_text": "\n".join(hierarchy_text_lines),
        }

        return MotionClip(
            skeleton=skeleton,
            timebase=timebase,
            local_rot=local_rot,
            root_pos=root_pos,
            extra_pos=extra_pos,
            codec_context=context,
        )

    def write(self, clip: MotionClip, output_path: Path | str, template_path: Optional[Path | str] = None) -> None:
        p = Path(output_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)

        hierarchy_text = clip.codec_context.get("hierarchy_text")
        channels_list = clip.codec_context.get("channels_list")

        if not hierarchy_text or not channels_list:
            # Build default minimal hierarchy if template text is missing
            hierarchy_lines = ["HIERARCHY"]
            built_channels = []
            for j, name in enumerate(clip.skeleton.names):
                prefix = "ROOT" if j == 0 else "JOINT"
                hierarchy_lines.append(f"{prefix} {name}\n{{")
                off = clip.skeleton.rest_offsets[j]
                hierarchy_lines.append(f"  OFFSET {off[0]:.6f} {off[1]:.6f} {off[2]:.6f}")
                order = clip.skeleton.rotation_orders[j]
                if j == 0:
                    ch = ["Xposition", "Yposition", "Zposition"] + [f"{axis}rotation" for axis in order]
                else:
                    ch = [f"{axis}rotation" for axis in order]
                hierarchy_lines.append(f"  CHANNELS {len(ch)} {' '.join(ch)}")
                built_channels.append(ch)
            for _ in range(len(clip.skeleton.names)):
                hierarchy_lines.append("}")
            hierarchy_text = "\n".join(hierarchy_lines)
            channels_list = built_channels

        frame_time = clip.timebase.frame_duration_sec
        total_frames = clip.frame_count

        lines = [
            hierarchy_text,
            "MOTION",
            f"Frames: {total_frames}",
            f"Frame Time: {frame_time:.8f}",
        ]

        # Convert rotations to Euler angles
        J = clip.skeleton.joint_count
        euler_per_joint = []
        for j in range(J):
            order = clip.skeleton.rotation_orders[j]
            r = Rotation.from_quat(clip.local_rot[:, j, :])
            angles = r.as_euler(order.lower(), degrees=True)
            unwrapped = unwrap_euler(angles)
            euler_per_joint.append(unwrapped)

        for f_idx in range(total_frames):
            row_tokens = []
            for j in range(J):
                chans = channels_list[j]
                if not chans:
                    continue
                # Position channels
                if any(c.upper().endswith("POSITION") for c in chans):
                    pos = clip.root_pos[f_idx] if j == 0 else clip.extra_pos.get(j, np.zeros(3))[f_idx]
                    row_tokens.extend([f"{pos[0]:.6f}", f"{pos[1]:.6f}", f"{pos[2]:.6f}"])
                # Rotation channels
                if any(c.upper().endswith("ROTATION") for c in chans):
                    angs = euler_per_joint[j][f_idx]
                    row_tokens.extend([f"{angs[0]:.6f}", f"{angs[1]:.6f}", f"{angs[2]:.6f}"])

            lines.append(" ".join(row_tokens))

        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
