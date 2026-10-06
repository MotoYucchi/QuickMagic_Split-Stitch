"""Unit tests for SessionManifest serialization, schema validation, and round-trip fidelity."""

from __future__ import annotations

from pathlib import Path
import pytest
from pydantic import ValidationError

from splitstitch.core.manifest import (
    ChunkInfo,
    ColorInfo,
    EncodeParams,
    OverlapConfig,
    PlanConfig,
    SessionManifest,
    SessionTotals,
    SourceMetadata,
)


def create_sample_manifest(session_id: str = "test_session_01") -> SessionManifest:
    source = SourceMetadata(
        path="dance_60fps.mov",
        size_bytes=500_000_000,
        fingerprint="dummy_fp",
        width=1920,
        height=1080,
        rotation=0,
        fps="60/1",
        vfr=False,
        frame_count=1800,
        first_frame_pts_sec=0.0,
        color=ColorInfo(transfer="bt709", hdr=False, pix_fmt="yuv420p"),
    )
    plan = PlanConfig(
        name="free",
        mode="stretch",
        declared_fps="30/1",
        stretch_ratio="2/1",
        resolution_policy="auto",
        output_resolution=(1920, 1080),
        quality_preset="high",
        encode=EncodeParams(codec="libx264", crf=18, maxrate_kbps=12000, bufsize_kbps=12000, preset="slow"),
    )
    overlap = OverlapConfig(source_frames=60, guard_upload_frames=8, blend_source_frames=30)
    chunks = [
        ChunkInfo(
            index=1,
            filename="chunk_001.mp4",
            source_frame_range=(0, 900),
            upload_frame_count=900,
            upload_duration_sec=30.0,
            status="verified",
            size_bytes=42_000_000,
            sha256="abcdef123456",
        ),
        ChunkInfo(
            index=2,
            filename="chunk_002.mp4",
            source_frame_range=(840, 1740),
            upload_frame_count=900,
            upload_duration_sec=30.0,
            status="verified",
            size_bytes=41_500_000,
            sha256="123456abcdef",
        ),
    ]
    totals = SessionTotals(chunk_count=2, upload_seconds=60.0, upload_bytes=83_500_000)

    return SessionManifest(
        session_id=session_id,
        created_at="2026-10-07T00:00:00Z",
        source=source,
        plan=plan,
        overlap=overlap,
        chunks=chunks,
        totals=totals,
    )


def test_manifest_json_roundtrip(tmp_path: Path) -> None:
    """Verify SessionManifest saves and loads identically from disk."""
    manifest = create_sample_manifest()
    m_path = tmp_path / "session_manifest.json"
    manifest.save(m_path)
    assert m_path.is_file()

    loaded = SessionManifest.load(m_path)
    assert loaded.session_id == manifest.session_id
    assert len(loaded.chunks) == 2
    assert loaded.chunks[0].filename == "chunk_001.mp4"
    assert loaded.source.width == 1920
    assert loaded.plan.declared_fps == "30/1"
    assert loaded.totals.chunk_count == 2


def test_manifest_missing_required_field_raises(tmp_path: Path) -> None:
    """Verify loading corrupted JSON without required fields raises ValidationError."""
    bad_json = tmp_path / "corrupt_manifest.json"
    bad_json.write_text('{"session_id": "bad", "chunks": []}', encoding="utf-8")

    with pytest.raises(ValidationError):
        SessionManifest.load(bad_json)
