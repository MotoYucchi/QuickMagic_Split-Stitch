"""Split & Stitch for QuickMagicMotion - Command Line Interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from splitstitch.core.encoder import EncodeProgress, run_ffmpeg_encode
from splitstitch.core.ffmpeg_cmd import build_ffmpeg_chunk_cmd
from splitstitch.core.manifest import SessionManifest
from splitstitch.core.planner import plan_splitting
from splitstitch.core.probe import probe_video
from splitstitch.core.session import create_initial_manifest, setup_session_directory
from splitstitch.core.verifier import verify_chunk
from splitstitch.motion.stitch import match_motion_files_to_chunks, stitch_motion_session

app = typer.Typer(
    name="splitstitch",
    help="Split & Stitch for QuickMagicMotion: High-Precision Splitting & Motion Stitching Pipeline",
    add_completion=False,
)
console = Console()


@app.command()
def probe(
    video: Path = typer.Argument(..., help="Path to video file"),
    as_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Analyze video stream metadata: resolution, rotation, HDR, FPS, and VFR."""
    try:
        res = probe_video(video)
        if as_json:
            data = {
                "path": str(res.path),
                "width": res.width,
                "height": res.height,
                "rotation": res.rotation,
                "display_resolution": f"{res.display_width}x{res.display_height}",
                "fps": f"{res.fps.numerator}/{res.fps.denominator}",
                "nominal_fps": float(res.fps),
                "is_vfr": res.is_vfr,
                "frame_count": res.frame_count,
                "duration_sec": round(res.duration_sec, 3),
                "is_hdr": res.is_hdr,
                "pix_fmt": res.pix_fmt,
            }
            console.print(json.dumps(data, indent=2))
            return

        table = Table(title=f"Video Analysis: {video.name}", show_header=True)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Resolution", f"{res.display_width} x {res.display_height} (Raw: {res.width}x{res.height})")
        table.add_row("Rotation", f"{res.rotation}°")
        table.add_row("Frame Rate", f"{res.fps} ({float(res.fps):.3f} fps)")
        table.add_row("Rate Mode", "Variable Frame Rate (VFR)" if res.is_vfr else "Constant Frame Rate (CFR)")
        table.add_row("Total Frames", str(res.frame_count))
        table.add_row("Duration", f"{res.duration_sec:.2f} s")
        table.add_row("HDR / 10-bit", "Yes (HDR)" if res.is_hdr else "No (SDR)")
        table.add_row("Pixel Format", res.pix_fmt)

        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error probing video:[/bold red] {e}")
        sys.exit(3)


@app.command()
def plan(
    video: Path = typer.Option(..., "--input", "-i", help="Path to source video file"),
    plan_name: str = typer.Option("free", "--plan", "-p", help="Target plan: free, basic, pro, max, studio"),
    mode: str = typer.Option("stretch", "--mode", "-m", help="Mode: stretch (preserve all frames) or native"),
    resolution: str = typer.Option("auto", "--resolution", "-r", help="Resolution: auto, keep, 1080, 1440"),
    quality: str = typer.Option("high", "--quality", "-q", help="Quality: high, balanced, compact"),
    overlap_sec: float = typer.Option(1.0, "--overlap-sec", help="Overlap duration in real seconds"),
    as_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Preview splitting plan (Dry run without encoding)."""
    try:
        p_res = probe_video(video)
        out = plan_splitting(
            probe=p_res,
            plan_name=plan_name,
            mode=mode,
            resolution_policy=resolution,
            quality_preset=quality,
            overlap_sec=overlap_sec,
        )

        if as_json:
            console.print(out.plan_config.model_dump_json(indent=2))
            return

        table = Table(title=f"Splitting Plan Preview: {video.name} ({plan_name.title()} Plan)", show_header=True)
        table.add_column("Chunk #", style="cyan")
        table.add_column("Source Frames [start, end)", style="magenta")
        table.add_column("Upload Frames", style="blue")
        table.add_column("Upload Duration", style="green")
        table.add_column("Est. Max Size", style="yellow")

        for c in out.chunks:
            table.add_row(
                f"#{c.index}",
                f"[{c.source_start_frame}, {c.source_end_frame})",
                str(c.upload_frame_count),
                f"{c.upload_duration_sec:.1f} s",
                f"~{out.estimated_size_per_chunk_mb:.1f} MB",
            )

        console.print(table)
        console.print(
            f"[bold]Totals:[/bold] [green]{out.totals.chunk_count} chunks[/green] | "
            f"Quota Duration: [yellow]{out.totals.upload_seconds:.1f} s[/yellow] | "
            f"Bitrate: [cyan]{out.bitrate_kbps} kbps[/cyan]"
        )
    except Exception as e:
        console.print(f"[bold red]Planning failed:[/bold red] {e}")
        sys.exit(4)


@app.command()
def split(
    video: Path = typer.Option(..., "--input", "-i", help="Path to input video file"),
    outdir: Path = typer.Option(..., "--outdir", "-o", help="Session output directory"),
    plan_name: str = typer.Option("free", "--plan", "-p", help="Target plan: free, basic, pro, max, studio"),
    mode: str = typer.Option("stretch", "--mode", "-m", help="Mode: stretch (preserve all frames) or native"),
    resolution: str = typer.Option("auto", "--resolution", "-r", help="Resolution policy"),
    quality: str = typer.Option("high", "--quality", "-q", help="Quality preset"),
    overlap_sec: float = typer.Option(1.0, "--overlap-sec", help="Overlap in seconds"),
    resume: bool = typer.Option(False, "--resume", help="Skip already verified chunks"),
) -> None:
    """Split and optimize video into upload-ready chunks adhering to plan capacity."""
    try:
        console.print(f"[bold blue]Probing source video:[/bold blue] {video}")
        p_res = probe_video(video)

        console.print(f"[bold blue]Calculating split plan ({plan_name.title()})...[/bold blue]")
        p_out = plan_splitting(
            probe=p_res,
            plan_name=plan_name,
            mode=mode,
            resolution_policy=resolution,
            quality_preset=quality,
            overlap_sec=overlap_sec,
        )

        session_paths = setup_session_directory(outdir, use_exact_dir=True)
        manifest = create_initial_manifest(p_res, p_out, session_paths.root_dir.name)

        console.print(
            f"[green]Session initialized at:[/green] {session_paths.root_dir}\n"
            f"Generating [bold]{len(manifest.chunks)}[/bold] chunks..."
        )

        # Iterate and encode chunks
        for idx, chunk in enumerate(manifest.chunks, start=1):
            chunk_file = session_paths.upload_dir / chunk.filename

            if resume and chunk_file.is_file():
                v_res = verify_chunk(chunk_file, chunk, p_out.plan_config.encode.maxrate_kbps * 1000)
                if v_res.is_valid:
                    console.print(f"[cyan]Chunk #{idx} already verified, skipping.[/cyan]")
                    chunk.status = "verified"
                    chunk.size_bytes = v_res.file_size_bytes
                    chunk.sha256 = v_res.sha256
                    continue

            cmd = build_ffmpeg_chunk_cmd(
                probe=p_res,
                chunk=chunk,
                plan_config=manifest.plan,
                output_path=chunk_file,
                session_id=manifest.session_id,
            )
            chunk.ffmpeg_args = cmd

            with Progress(
                SpinnerColumn(),
                TextColumn(f"[bold cyan]Encoding Chunk #{idx}/{len(manifest.chunks)}:"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("Speed: {task.fields[speed]}"),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("encode", total=chunk.upload_frame_count, speed="1.0x")

                def on_prog(p: EncodeProgress) -> None:
                    progress.update(task, completed=p.current_frame, speed=p.speed)

                run_ffmpeg_encode(cmd, total_frames=chunk.upload_frame_count, on_progress=on_prog)

            # Verification
            # Get max allowed bytes for plan
            spec_max_bytes = 50 * 1000 * 1000 if plan_name == "free" else 500 * 1000 * 1000
            v_res = verify_chunk(chunk_file, chunk, spec_max_bytes)

            if not v_res.is_valid:
                console.print(f"[bold red]Verification failed for chunk #{idx}:[/bold red] {v_res.error_message}")
                chunk.status = "failed"
                manifest.save(session_paths.manifest_file)
                sys.exit(5)

            chunk.status = "verified"
            chunk.size_bytes = v_res.file_size_bytes
            chunk.sha256 = v_res.sha256
            console.print(f"[green]Chunk #{idx} verified successfully ({v_res.file_size_bytes / 1e6:.1f} MB).[/green]")

        # Update totals & save final manifest
        manifest.totals.upload_bytes = sum(c.size_bytes for c in manifest.chunks)
        manifest.save(session_paths.manifest_file)

        console.print(f"\n[bold green]Splitting complete![/bold green] Upload chunks located in:\n[cyan]{session_paths.upload_dir}[/cyan]")
    except Exception as e:
        console.print(f"[bold red]Error during splitting:[/bold red] {e}")
        sys.exit(1)


@app.command()
def verify(
    session: Path = typer.Option(..., "--session", "-s", help="Path to session folder containing session_manifest.json"),
) -> None:
    """Verify integrity of all encoded chunk files against manifest."""
    try:
        m_file = session / "session_manifest.json" if session.is_dir() else session
        manifest = SessionManifest.load(m_file)
        upload_dir = m_file.parent / "upload"

        all_ok = True
        for chunk in manifest.chunks:
            c_path = upload_dir / chunk.filename
            res = verify_chunk(c_path, chunk, 500 * 1000 * 1000)
            if res.is_valid:
                console.print(f"[green]Chunk #{chunk.index}: OK[/green] ({res.actual_frames} frames, {res.file_size_bytes/1e6:.2f} MB)")
            else:
                console.print(f"[bold red]Chunk #{chunk.index}: FAILED[/bold red] - {res.error_message}")
                all_ok = False

        if not all_ok:
            sys.exit(5)
        console.print("[bold green]All chunks verified successfully![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Verification failed:[/bold red] {e}")
        sys.exit(1)


@app.command(name="stitch")
def stitch(
    manifest_path: Path = typer.Option(..., "--manifest", "-m", help="Path to session_manifest.json"),
    motion_dir: Path = typer.Option(..., "--motion-dir", "-d", help="Directory containing downloaded motion files"),
    output: Path = typer.Option(..., "--output", "-o", help="Path for merged output motion file (.fbx, .bvh, .vmd)"),
    fps: Optional[str] = typer.Option(None, "--fps", help="Target output frame rate (default: restore source FPS)"),
    blend_sec: float = typer.Option(0.5, "--blend-sec", help="Blend window duration in seconds"),
    easing: str = typer.Option("smoothstep", "--easing", help="Easing curve: smoothstep, linear, cosine"),
    align: str = typer.Option("yaw+xz", "--align", help="Rigid alignment: yaw+xz, xz, none"),
    vertical: str = typer.Option("keep", "--vertical", help="Vertical alignment: keep or align"),
    seam: str = typer.Option("auto", "--seam", help="Seam search mode: auto or center"),
    report: Optional[Path] = typer.Option(None, "--report", help="Path for QC report (.html or .json)"),
) -> None:
    """Stitch multiple motion files back into a single continuous high-fidelity motion."""
    try:
        manifest = SessionManifest.load(manifest_path)
        motion_files = match_motion_files_to_chunks(manifest, motion_dir)

        console.print(f"Matched [bold green]{len(motion_files)}[/bold green] motion files for stitching.")

        def on_prog(cur: int, total: int, msg: str) -> None:
            console.print(f"[cyan][{cur}/{total}][/cyan] {msg}")

        qc_rep = stitch_motion_session(
            manifest=manifest,
            motion_files=motion_files,
            output_path=output,
            target_fps=fps,
            blend_sec=blend_sec,
            easing=easing,
            align_mode=align,
            vertical_mode=vertical,
            seam_mode=seam,
            report_path=report,
            on_progress=on_prog,
        )

        console.print(f"\n[bold green]Stitching completed successfully![/bold green] Output: [cyan]{output}[/cyan]")
        console.print(f"Total Duration: [yellow]{qc_rep.total_duration_sec:.2f} s[/yellow] ({qc_rep.total_frames} frames)")
        console.print(f"Status: [{'green' if qc_rep.overall_status == 'clean' else 'yellow'}]{qc_rep.overall_status.upper()}[/]")
    except Exception as e:
        console.print(f"[bold red]Stitching error:[/bold red] {e}")
        sys.exit(7)


# Alias merge to stitch
app.command(name="merge", hidden=True)(stitch)


@app.command()
def gui() -> None:
    """Launch Split & Stitch Graphical User Interface."""
    from splitstitch.gui.app import launch_gui
    launch_gui()


if __name__ == "__main__":
    app()
