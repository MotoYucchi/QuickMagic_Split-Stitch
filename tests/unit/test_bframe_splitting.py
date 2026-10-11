import subprocess
from pathlib import Path
import pytest

from splitstitch.core.probe import get_ffmpeg_path, probe_video
from splitstitch.core.planner import plan_splitting
from splitstitch.core.ffmpeg_cmd import build_ffmpeg_chunk_cmd
from splitstitch.core.verifier import count_video_frames, verify_chunk


def test_bframe_video_multichunk_splitting(tmp_path: Path):
    """Regression test: Ensure multi-chunk splitting works accurately on B-frame video without timestamp misordering or frame loss."""
    ffmpeg = get_ffmpeg_path()
    src_video = tmp_path / "bframe_video.mp4"

    # Generate 45 seconds (1350 frames at 30fps) with B-frames (-bf 2)
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=45",
        "-c:v", "libx264", "-bf", "2", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src_video)
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    probe = probe_video(src_video)
    assert not probe.timeline.is_vfr, "B-frame CFR video should not be detected as VFR"

    planner_out = plan_splitting(probe, plan_name="free", mode="stretch")
    assert len(planner_out.chunks) >= 2

    for chunk in planner_out.chunks:
        chunk_out = tmp_path / chunk.filename
        cmd = build_ffmpeg_chunk_cmd(probe, chunk, planner_out.plan_config, chunk_out, "test_bframe")
        preset_idx = cmd.index("-preset")
        cmd[preset_idx + 1] = "ultrafast"
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        actual_frames = count_video_frames(chunk_out)
        assert actual_frames == chunk.upload_frame_count, (
            f"Chunk #{chunk.index} frame mismatch: got {actual_frames}, expected {chunk.upload_frame_count}"
        )

        v_res = verify_chunk(chunk_out, chunk, 500 * 1000 * 1000)
        assert v_res.is_valid, f"Chunk #{chunk.index} failed: {v_res.error_message}"
