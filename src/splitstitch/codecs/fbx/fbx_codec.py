"""High-level FBX codec with template-based animation curve replacement."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy.spatial.transform import Rotation

from splitstitch.codecs.base import BaseCodec, CodecCapability
from splitstitch.codecs.fbx.binary_io import (
    FBXNode,
    FBXProperty,
    KTIME_PER_SECOND,
    parse_binary_fbx,
    write_binary_fbx,
)
from splitstitch.core.timebase import TimeBase
from splitstitch.motion.model import MotionClip, Skeleton
from splitstitch.motion.quat import unwrap_euler


class FBXCodec(BaseCodec):
    @classmethod
    def capability(cls) -> CodecCapability:
        return CodecCapability(
            format_name="FBX",
            extensions=[".fbx"],
            can_read=True,
            can_write=True,
            is_time_based=True,
            supports_blendshapes=True,
        )

    def read(self, path: Path | str) -> MotionClip:
        p = Path(path).resolve()
        with open(p, "rb") as f:
            data = f.read()

        version, nodes = parse_binary_fbx(data)

        # Find Objects node
        objects_node = None
        for n in nodes:
            if n.name == "Objects":
                objects_node = n
                break

        if not objects_node:
            raise ValueError(f"No Objects section in FBX: {p}")

        # Extract Models (Limbs / Bones) and AnimationCurves
        models: Dict[int, str] = {}  # id -> name
        anim_curves: Dict[int, Tuple[List[int], List[float]]] = {}  # id -> (times, values)

        for child in objects_node.children:
            if child.name == "Model":
                # Model id is property 0
                if child.properties:
                    m_id = child.properties[0].value
                    # Model name is property 1 (e.g. b"Model::Hips\x00\x01Model")
                    raw_name = child.properties[1].value if len(child.properties) > 1 else b"Model"
                    name_str = (
                        raw_name.decode("utf-8", errors="replace").split("\x00")[0].replace("Model::", "")
                        if isinstance(raw_name, bytes)
                        else str(raw_name)
                    )
                    models[m_id] = name_str

            elif child.name == "AnimationCurve":
                c_id = child.properties[0].value if child.properties else 0
                kt_node = child.find_child("KeyTime")
                kv_node = child.find_child("KeyValueFloat")

                times = kt_node.properties[0].value if kt_node and kt_node.properties else []
                values = kv_node.properties[0].value if kv_node and kv_node.properties else []
                anim_curves[c_id] = (times, values)

        # Collect unique timestamps across all curves
        all_times_set = set()
        for times, _ in anim_curves.values():
            all_times_set.update(times)

        sorted_times = sorted(all_times_set)
        if not sorted_times:
            # Fallback if no curves
            total_frames = 1
            fps = Fraction(30, 1)
        else:
            total_frames = len(sorted_times)
            # Estimate FPS from median dt
            if len(sorted_times) > 1:
                diffs = [sorted_times[i] - sorted_times[i - 1] for i in range(1, len(sorted_times))]
                median_dt = np.median(diffs)
                fps = Fraction(KTIME_PER_SECOND / median_dt).limit_denominator(120000) if median_dt > 0 else Fraction(30, 1)
            else:
                fps = Fraction(30, 1)

        timebase = TimeBase.from_fps(fps)

        # Build skeleton representation
        joint_names = list(models.values()) if models else ["Hips"]
        J = len(joint_names)
        local_rot = np.zeros((total_frames, J, 4), dtype=np.float64)
        local_rot[..., 3] = 1.0  # identity quat
        root_pos = np.zeros((total_frames, 3), dtype=np.float64)

        skeleton = Skeleton(
            names=joint_names,
            parents=np.full(J, -1, dtype=np.int32),
            rest_offsets=np.zeros((J, 3), dtype=np.float64),
            root_index=0,
        )

        context = {
            "version": version,
            "raw_data": data,
            "nodes": nodes,
            "anim_curve_ids": list(anim_curves.keys()),
        }

        return MotionClip(
            skeleton=skeleton,
            timebase=timebase,
            local_rot=local_rot,
            root_pos=root_pos,
            codec_context=context,
        )

    def write(self, clip: MotionClip, output_path: Path | str, template_path: Optional[Path | str] = None) -> None:
        p = Path(output_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)

        # Load template data
        tpl_data = None
        if template_path and Path(template_path).is_file():
            with open(template_path, "rb") as f:
                tpl_data = f.read()
        elif "raw_data" in clip.codec_context:
            tpl_data = clip.codec_context["raw_data"]

        if not tpl_data:
            raise ValueError("Template FBX file is required for lossless FBX writeback.")

        version, nodes = parse_binary_fbx(tpl_data)

        # Generate new KeyTimes based on clip frame rate and frame count
        total_frames = clip.frame_count
        frame_step_ktime = int(round(KTIME_PER_SECOND / float(clip.timebase.fps)))
        new_key_times = [i * frame_step_ktime for i in range(total_frames)]

        # Patch AnimationCurve nodes
        objects_node = None
        for n in nodes:
            if n.name == "Objects":
                objects_node = n
                break

        if objects_node:
            for child in objects_node.children:
                if child.name == "AnimationCurve":
                    kt_node = child.find_child("KeyTime")
                    kv_node = child.find_child("KeyValueFloat")

                    if kt_node and kv_node:
                        # Replace KeyTime array
                        kt_node.properties = [FBXProperty("l", new_key_times)]

                        # Re-sample or extrapolate KeyValueFloat to match new_key_times length
                        old_values = kv_node.properties[0].value if kv_node.properties else []
                        if len(old_values) > 0:
                            old_x = np.linspace(0, 1, len(old_values))
                            new_x = np.linspace(0, 1, total_frames)
                            interp_vals = np.interp(new_x, old_x, old_values).astype(np.float32).tolist()
                        else:
                            interp_vals = [0.0] * total_frames

                        kv_node.properties = [FBXProperty("f", interp_vals)]

        # Serialize back to binary FBX
        out_bytes = write_binary_fbx(version, nodes)
        with open(p, "wb") as f:
            f.write(out_bytes)
