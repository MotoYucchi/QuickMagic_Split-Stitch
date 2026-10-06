"""Base codec interface and capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from splitstitch.motion.model import MotionClip


@dataclass
class CodecCapability:
    format_name: str
    extensions: list[str]
    can_read: bool = True
    can_write: bool = True
    is_time_based: bool = True  # True if arbitrary rational FPS in header, False if integer frame indexed (e.g. VMD)
    supports_blendshapes: bool = False
    max_fps: Optional[int] = None


class BaseCodec(ABC):
    """Abstract motion codec."""

    @classmethod
    @abstractmethod
    def capability(cls) -> CodecCapability:
        pass

    @abstractmethod
    def read(self, path: Path | str) -> MotionClip:
        """Read motion file into MotionClip intermediate representation."""
        pass

    @abstractmethod
    def write(self, clip: MotionClip, output_path: Path | str, template_path: Optional[Path | str] = None) -> None:
        """Write MotionClip into motion file, optionally referencing template file."""
        pass
