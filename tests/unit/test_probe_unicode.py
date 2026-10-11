import subprocess
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from splitstitch.core.probe import get_ffmpeg_version, probe_video
from splitstitch.core.verifier import count_video_frames


def test_ffmpeg_version_non_ascii_bytes():
    # Simulate non-ascii bytes that would crash cp932 decoder if text=True were used
    mock_res = MagicMock()
    mock_res.stdout = b"ffmpeg version 7.0.2 \x84\x90\xaa copyright\n"
    with patch("subprocess.run", return_value=mock_res):
        ver = get_ffmpeg_version()
        assert ver == "7.0.2"


def test_probe_video_handles_multibyte_stdout(tmp_path: Path):
    dummy_video = tmp_path / "test.mp4"
    dummy_video.touch()

    # Valid JSON in bytes with some multibyte characters in tags or stream info
    json_bytes = b'''{
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "time_base": "1/1000",
                "nb_frames": "300",
                "tags": {"title": "\xe3\x83\x86\xe3\x82\xb9\xe3\x83\x88"}
            }
        ],
        "format": {
            "duration": "10.0",
            "size": "1048576"
        }
    }'''

    mock_res = MagicMock()
    mock_res.stdout = json_bytes

    with patch("subprocess.run", return_value=mock_res):
        res = probe_video(dummy_video, fast=True)
        assert res.width == 1920
        assert res.height == 1080
        assert res.frame_count == 300
