"""End-to-End integration test covering split, verify, and stitch with actual FFmpeg."""

import subprocess
from pathlib import Path
import numpy as np
import pytest

from splitstitch.codecs.bvh import BVHCodec
from splitstitch.core.manifest import SessionManifest
from splitstitch.core.probe import get_ffmpeg_path, probe_video
from splitstitch.core.timebase import TimeBase
from splitstitch.motion.model import MotionClip, Skeleton
from splitstitch.motion.stitch import stitch_motion_session


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 5-second 60fps 1080p test video with frame numbers burnt-in."""
    tmp = tmp_path_factory.mktemp("media")
    video_path = tmp / "test_60fps.mp4"
    ffmpeg = get_ffmpeg_path()

    # Generate 5 seconds at 60 fps (300 frames)
    cmd = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=size=1920x1080:rate=60:duration=5",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return video_path


def test_full_pipeline_e2e(sample_video: Path, tmp_path: Path) -> None:
    # 1. Probe
    probe_res = probe_video(sample_video)
    assert probe_res.width == 1920
    assert probe_res.height == 1080
    assert probe_res.frame_count == 300
    assert float(probe_res.fps) == 60.0

    # 2. Split with Free plan and stretch mode
    session_dir = tmp_path / "session_e2e"
    from typer.testing import CliRunner
    from splitstitch.cli.main import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "split",
            "--input", str(sample_video),
            "--outdir", str(session_dir),
            "--plan", "free",
            "--mode", "stretch",
            "--overlap-sec", "0.5",
        ],
    )
    assert result.exit_code == 0, f"Split CLI failed:\n{result.stdout}"

    manifest_file = session_dir / "session_manifest.json"
    assert manifest_file.is_file()

    manifest = SessionManifest.load(manifest_file)
    assert manifest.plan.mode == "stretch"
    assert manifest.plan.declared_fps == "30/1"
    assert manifest.plan.stretch_ratio == "2/1"
    assert len(manifest.chunks) >= 1

    # 3. Verify
    v_result = runner.invoke(app, ["verify", "--session", str(session_dir)])
    assert v_result.exit_code == 0, f"Verify CLI failed:\n{v_result.stdout}"

    # 4. Create mock motion clips matching chunks
    # Since Stretch ratio is 2, 60fps video becomes 30fps video uploaded to QuickMagic.
    # QuickMagic exports 30fps motion with upload_frame_count frames.
    motions_dir = tmp_path / "downloaded_motions"
    motions_dir.mkdir(parents=True, exist_ok=True)

    names = ["Hips", "Spine"]
    skeleton = Skeleton(
        names=names,
        parents=np.array([-1, 0], dtype=np.int32),
        rest_offsets=np.array([[0, 0, 0], [0, 1, 0]], dtype=np.float64),
        root_index=0,
    )
    codec = BVHCodec()

    for chunk in manifest.chunks:
        F = chunk.upload_frame_count
        tb = TimeBase.from_fps(30)
        local_rot = np.zeros((F, 2, 4), dtype=np.float64)
        local_rot[..., 3] = 1.0  # identity
        root_pos = np.zeros((F, 3), dtype=np.float64)
        # Position moves smoothly based on source frame
        for f in range(F):
            src_f = chunk.source_start_frame + f
            root_pos[f, :] = [src_f * 0.01, 1.0, 0.0]

        clip = MotionClip(skeleton=skeleton, timebase=tb, local_rot=local_rot, root_pos=root_pos)
        out_bvh = motions_dir / f"chunk_{chunk.index:03d}of{len(manifest.chunks):03d}.bvh"
        codec.write(clip, out_bvh)

    # 5. Stitch
    final_output = tmp_path / "final_merged_60fps.bvh"
    qc_report_path = tmp_path / "qc_report.html"

    s_result = runner.invoke(
        app,
        [
            "stitch",
            "--manifest", str(manifest_file),
            "--motion-dir", str(motions_dir),
            "--output", str(final_output),
            "--blend-sec", "0.2",
            "--report", str(qc_report_path),
        ],
    )
    assert s_result.exit_code == 0, f"Stitch CLI failed:\n{s_result.stdout}"
    assert final_output.is_file()
    assert qc_report_path.is_file()

    # Read final output and verify
    merged_clip = codec.read(final_output)
    # Stitched clip timebase should be restored to 60fps!
    assert float(merged_clip.timebase.fps) == 60.0
    # Total frames should be close to original 300 frames
    assert abs(merged_clip.frame_count - 300) < 5
    assert merged_clip.duration_sec == pytest.approx(5.0, abs=0.1)
