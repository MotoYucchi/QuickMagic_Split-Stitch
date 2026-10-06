"""Verification of encoded chunk media files."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from splitstitch.core.manifest import ChunkInfo
from splitstitch.core.probe import get_ffprobe_path


@dataclass
class VerificationResult:
    chunk_index: int
    is_valid: bool
    actual_frames: int
    expected_frames: int
    file_size_bytes: int
    max_size_bytes: int
    sha256: str
    error_message: Optional[str] = None


def compute_sha256(path: Path | str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def count_video_frames(path: Path | str) -> int:
    """Count exact number of video frames using ffprobe count_frames."""
    ffprobe = get_ffprobe_path()
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-count_frames",
        "-show_entries", "stream=nb_read_frames,nb_frames",
        "-print_format", "json",
        str(path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError(f"No video streams found in {path}")
    st = streams[0]
    read_frames = st.get("nb_read_frames")
    if read_frames and str(read_frames).isdigit():
        return int(read_frames)
    nb_frames = st.get("nb_frames")
    if nb_frames and str(nb_frames).isdigit():
        return int(nb_frames)
    raise ValueError(f"Could not determine frame count for {path}")


def verify_chunk(
    chunk_path: Path | str,
    chunk_info: ChunkInfo,
    max_allowed_bytes: int,
) -> VerificationResult:
    """Verify chunk size, frame count, and checksum."""
    p = Path(chunk_path).resolve()
    if not p.is_file():
        return VerificationResult(
            chunk_index=chunk_info.index,
            is_valid=False,
            actual_frames=0,
            expected_frames=chunk_info.upload_frame_count,
            file_size_bytes=0,
            max_size_bytes=max_allowed_bytes,
            sha256="",
            error_message=f"Chunk file does not exist: {p}",
        )

    file_size = p.stat().st_size
    if file_size > max_allowed_bytes:
        return VerificationResult(
            chunk_index=chunk_info.index,
            is_valid=False,
            actual_frames=0,
            expected_frames=chunk_info.upload_frame_count,
            file_size_bytes=file_size,
            max_size_bytes=max_allowed_bytes,
            sha256="",
            error_message=f"File size {file_size} exceeds max limit {max_allowed_bytes} bytes",
        )

    try:
        actual_frames = count_video_frames(p)
    except Exception as e:
        return VerificationResult(
            chunk_index=chunk_info.index,
            is_valid=False,
            actual_frames=0,
            expected_frames=chunk_info.upload_frame_count,
            file_size_bytes=file_size,
            max_size_bytes=max_allowed_bytes,
            sha256="",
            error_message=f"Failed counting video frames: {e}",
        )

    if actual_frames != chunk_info.upload_frame_count:
        return VerificationResult(
            chunk_index=chunk_info.index,
            is_valid=False,
            actual_frames=actual_frames,
            expected_frames=chunk_info.upload_frame_count,
            file_size_bytes=file_size,
            max_size_bytes=max_allowed_bytes,
            sha256="",
            error_message=(
                f"Frame count mismatch: got {actual_frames}, expected {chunk_info.upload_frame_count}"
            ),
        )

    sha = compute_sha256(p)
    return VerificationResult(
        chunk_index=chunk_info.index,
        is_valid=True,
        actual_frames=actual_frames,
        expected_frames=chunk_info.upload_frame_count,
        file_size_bytes=file_size,
        max_size_bytes=max_allowed_bytes,
        sha256=sha,
    )
