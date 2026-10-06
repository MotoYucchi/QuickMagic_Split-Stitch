"""Session lifecycle and directory management."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from splitstitch.core.manifest import (
    ColorInfo,
    OverlapConfig,
    PlanConfig,
    SessionManifest,
    SessionTotals,
    SourceMetadata,
    ToolInfo,
)
from splitstitch.core.planner import PlannerOutput
from splitstitch.core.probe import ProbeResult, get_ffmpeg_path
from splitstitch.core.timebase import format_fraction


@dataclass
class SessionPaths:
    root_dir: Path
    manifest_file: Path
    upload_dir: Path
    logs_dir: Path
    preview_dir: Path


def generate_session_id() -> str:
    """Generate unique session ID."""
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"qm_{now_str}_{short_uuid}"


def setup_session_directory(
    base_output_dir: Path | str,
    session_id: Optional[str] = None,
    use_exact_dir: bool = False,
) -> SessionPaths:
    """Create directory structure for a new or resumed session."""
    base = Path(base_output_dir).resolve()
    sid = session_id or generate_session_id()

    if use_exact_dir or base.name.startswith("qm_") or (base / "session_manifest.json").exists():
        root = base
    else:
        root = base / sid

    upload_dir = root / "upload"
    logs_dir = root / "logs"
    preview_dir = root / "preview"

    for d in (root, upload_dir, logs_dir, preview_dir):
        d.mkdir(parents=True, exist_ok=True)

    manifest_file = root / "session_manifest.json"
    return SessionPaths(
        root_dir=root,
        manifest_file=manifest_file,
        upload_dir=upload_dir,
        logs_dir=logs_dir,
        preview_dir=preview_dir,
    )


def create_initial_manifest(
    probe: ProbeResult,
    planner_output: PlannerOutput,
    session_id: str,
    ffmpeg_version: Optional[str] = None,
) -> SessionManifest:
    """Create a fully typed SessionManifest from probe and planner results."""
    from splitstitch.core.probe import get_ffmpeg_version
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ff_ver = ffmpeg_version or get_ffmpeg_version()

    source_meta = SourceMetadata(
        path=str(probe.path),
        size_bytes=probe.size_bytes,
        width=probe.width,
        height=probe.height,
        rotation=probe.rotation,
        fps=format_fraction(probe.fps),
        vfr=probe.is_vfr,
        frame_count=probe.frame_count,
        first_frame_pts_sec=probe.first_pts_sec,
        color=ColorInfo(
            transfer=probe.color_transfer,
            hdr=probe.is_hdr,
            pix_fmt=probe.pix_fmt,
        ),
    )

    return SessionManifest(
        schema_version=1,
        tool=ToolInfo(
            name="splitstitch",
            version="0.1.0",
            ffmpeg_version=ff_ver,
        ),
        session_id=session_id,
        created_at=created_at,
        source=source_meta,
        plan=planner_output.plan_config,
        overlap=planner_output.overlap_config,
        chunks=planner_output.chunks,
        totals=planner_output.totals,
    )
