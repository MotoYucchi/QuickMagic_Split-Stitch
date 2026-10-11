import subprocess
from pathlib import Path
import pytest

from splitstitch.core.probe import get_ffmpeg_path, probe_video
from splitstitch.core.planner import plan_splitting
from splitstitch.core.ffmpeg_cmd import build_ffmpeg_chunk_cmd
from splitstitch.core.verifier import count_video_frames, verify_chunk


def test_chunk_slicing_exact_frames(tmp_path: Path):
    """Regression test: Ensure chunk slicing produces exact planned frame count without off-by-one errors."""
    ffmpeg = get_ffmpeg_path()
    src_video = tmp_path / "src_test_exact.mp4"

    # Generate 1000 frames video (30fps, 33.33s)
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=35",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src_video)
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    probe = probe_video(src_video)
    planner_out = plan_splitting(probe, plan_name="free", mode="stretch")

    # Pick chunk 0 and test exact 753 frames (the exact count reported by user)
    chunk = planner_out.chunks[0]
    chunk.source_frame_range = (0, 753)
    chunk.upload_frame_count = 753

    chunk_out = tmp_path / "chunk_001_exact.mp4"
    cmd = build_ffmpeg_chunk_cmd(probe, chunk, planner_out.plan_config, chunk_out, "test_session")

    # Fast encode for test
    preset_idx = cmd.index("-preset")
    cmd[preset_idx + 1] = "ultrafast"

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    actual_frames = count_video_frames(chunk_out)
    assert actual_frames == 753, f"Expected 753 frames, but got {actual_frames}"

    v_res = verify_chunk(chunk_out, chunk, 500 * 1000 * 1000)
    assert v_res.is_valid, f"Verification failed: {v_res.error_message}"
