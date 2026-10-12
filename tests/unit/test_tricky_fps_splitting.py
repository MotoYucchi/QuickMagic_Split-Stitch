import subprocess
from pathlib import Path
import pytest

from splitstitch.core.probe import get_ffmpeg_path, probe_video
from splitstitch.core.planner import plan_splitting
from splitstitch.core.ffmpeg_cmd import build_ffmpeg_chunk_cmd
from splitstitch.core.verifier import count_video_frames, verify_chunk


@pytest.mark.parametrize("fps_rate", ["59.94", "60", "59.999", "29.97", "23.976"])
def test_various_fps_chunk_splitting(tmp_path: Path, fps_rate: str):
    """Ensure chunk slicing never drops or duplicates frames across diverse non-integer and tricky FPS rates."""
    ffmpeg = get_ffmpeg_path()
    src_video = tmp_path / f"test_{fps_rate}.mp4"

    # Generate 15 seconds video with tricky frame rate
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate={fps_rate}:duration=15",
        "-c:v", "libx264", "-bf", "2", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src_video)
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    probe = probe_video(src_video)
    planner_out = plan_splitting(probe, plan_name="free", mode="stretch")

    for chunk in planner_out.chunks:
        chunk_out = tmp_path / f"{fps_rate}_{chunk.filename}"
        cmd = build_ffmpeg_chunk_cmd(probe, chunk, planner_out.plan_config, chunk_out, f"test_{fps_rate}")
        preset_idx = cmd.index("-preset")
        cmd[preset_idx + 1] = "ultrafast"
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        actual = count_video_frames(chunk_out)
        expected = chunk.upload_frame_count
        assert actual == expected, (
            f"FPS {fps_rate} chunk #{chunk.index} mismatch: got {actual}, expected {expected}"
        )

        v_res = verify_chunk(chunk_out, chunk, 500 * 1000 * 1000)
        assert v_res.is_valid, f"Verification failed for FPS {fps_rate} chunk #{chunk.index}: {v_res.error_message}"
