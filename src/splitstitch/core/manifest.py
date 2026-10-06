"""Session manifest schema and I/O using Pydantic v2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator


class ToolInfo(BaseModel):
    name: str = "splitstitch"
    version: str = "0.1.0"
    ffmpeg_version: Optional[str] = None


class ColorInfo(BaseModel):
    transfer: str = "bt709"
    hdr: bool = False
    pix_fmt: str = "yuv420p"


class SourceMetadata(BaseModel):
    path: str
    size_bytes: int
    fingerprint: Optional[str] = None
    width: int
    height: int
    rotation: int = 0
    fps: str  # Rational string e.g. "60/1" or "60000/1001"
    vfr: bool = False
    frame_count: int
    first_frame_pts_sec: float = 0.0
    color: ColorInfo = Field(default_factory=ColorInfo)


class EncodeParams(BaseModel):
    codec: str = "libx264"
    crf: int = 18
    maxrate_kbps: int = 12000
    bufsize_kbps: int = 12000
    preset: str = "slow"


class PlanConfig(BaseModel):
    name: str  # "free", "basic", "pro", "max", "studio", "custom"
    mode: str  # "stretch" or "native"
    declared_fps: str  # Rational string e.g. "30/1"
    stretch_ratio: str  # Rational string e.g. "2/1"
    resolution_policy: str = "auto"
    output_resolution: Tuple[int, int]
    quality_preset: str = "high"
    encode: EncodeParams = Field(default_factory=EncodeParams)


class OverlapConfig(BaseModel):
    source_frames: int
    guard_upload_frames: int = 8
    blend_source_frames: int


class ChunkInfo(BaseModel):
    index: int
    filename: str
    source_frame_range: Tuple[int, int]  # Half-open interval [start, end)
    upload_frame_count: int
    upload_duration_sec: float
    size_bytes: int = 0
    sha256: Optional[str] = None
    ffmpeg_args: List[str] = Field(default_factory=list)
    status: str = "planned"  # "planned", "encoded", "verified", "failed"

    @property
    def source_start_frame(self) -> int:
        return self.source_frame_range[0]

    @property
    def source_end_frame(self) -> int:
        return self.source_frame_range[1]

    @property
    def duration_frames(self) -> int:
        return self.source_end_frame - self.source_start_frame


class SessionTotals(BaseModel):
    chunk_count: int
    upload_seconds: float
    upload_bytes: int = 0


class SessionManifest(BaseModel):
    schema_version: int = 1
    tool: ToolInfo = Field(default_factory=ToolInfo)
    session_id: str
    created_at: str
    source: SourceMetadata
    plan: PlanConfig
    overlap: OverlapConfig
    chunks: List[ChunkInfo]
    totals: SessionTotals
    qc_summary: Optional[dict[str, Any]] = None

    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: Path | str) -> SessionManifest:
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)
