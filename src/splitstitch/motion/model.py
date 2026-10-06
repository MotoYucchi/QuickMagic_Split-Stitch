"""Common intermediate motion model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np

from splitstitch.core.timebase import TimeBase


@dataclass
class Skeleton:
    """Rig joint hierarchy and rest-pose offsets."""

    names: List[str]
    parents: np.ndarray  # shape (J,), root is -1
    rest_offsets: np.ndarray  # shape (J, 3)
    rotation_orders: List[str] = field(default_factory=list)  # e.g. "ZXY", "XYZ" per joint
    root_index: int = 0

    def __post_init__(self) -> None:
        if len(self.rotation_orders) == 0:
            self.rotation_orders = ["XYZ"] * len(self.names)

    @property
    def joint_count(self) -> int:
        return len(self.names)

    def find_joint(self, name: str) -> Optional[int]:
        name_lower = name.lower()
        for idx, n in enumerate(self.names):
            if n.lower() == name_lower:
                return idx
        return None


@dataclass
class MotionClip:
    """Discrete motion clip representing joint rotations, root positions, and curves."""

    skeleton: Skeleton
    timebase: TimeBase
    local_rot: np.ndarray  # shape (F, J, 4) quaternions (x, y, z, w)
    root_pos: np.ndarray  # shape (F, 3) internal coordinates: Y-up, meters
    extra_pos: Dict[int, np.ndarray] = field(default_factory=dict)  # other joints with translation
    curves: Dict[str, np.ndarray] = field(default_factory=dict)  # blendshapes / morph targets (F,)
    codec_context: Dict[str, Any] = field(default_factory=dict)  # raw file headers/templates for lossless writeback

    @property
    def frame_count(self) -> int:
        return self.local_rot.shape[0]

    @property
    def duration_sec(self) -> float:
        return self.timebase.frame_to_time(self.frame_count)

    def copy(self) -> MotionClip:
        return MotionClip(
            skeleton=self.skeleton,
            timebase=self.timebase,
            local_rot=self.local_rot.copy(),
            root_pos=self.root_pos.copy(),
            extra_pos={k: v.copy() for k, v in self.extra_pos.items()},
            curves={k: v.copy() for k, v in self.curves.items()},
            codec_context=dict(self.codec_context),
        )
