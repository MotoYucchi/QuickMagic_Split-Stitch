"""Quality control metrics and diagnostic reports for stitched motion."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional
import numpy as np

from splitstitch.motion.quat import quat_angle_diff


@dataclass
class SeamQCMetrics:
    seam_index: int  # 1-indexed (between chunk i and i+1)
    chunk_a_index: int
    chunk_b_index: int
    mean_angle_diff_deg: float
    max_angle_diff_deg: float
    yaw_correction_deg: float
    translation_correction_m: float
    temporal_lag: int
    accel_spike_ratio: float
    has_warning: bool
    warnings: List[str]


@dataclass
class MotionQCReport:
    total_seams: int
    passed_seams: int
    total_duration_sec: float
    total_frames: int
    seams: List[SeamQCMetrics]
    overall_status: str  # "clean", "warning", "error"

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def generate_html(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for s in self.seams:
            status_badge = (
                '<span style="color:#e53e3e;font-weight:bold;">Warning</span>'
                if s.has_warning
                else '<span style="color:#38a169;font-weight:bold;">Good</span>'
            )
            warn_text = "<br>".join(s.warnings) if s.warnings else "None"
            rows.append(
                f"""<tr>
                    <td>#{s.seam_index} (Chunks {s.chunk_a_index} &rarr; {s.chunk_b_index})</td>
                    <td>{status_badge}</td>
                    <td>{s.mean_angle_diff_deg:.2f}&deg;</td>
                    <td>{s.yaw_correction_deg:.2f}&deg;</td>
                    <td>{s.translation_correction_m:.3f} m</td>
                    <td>{s.temporal_lag} frames</td>
                    <td>{s.accel_spike_ratio:.2f}x</td>
                    <td style="font-size:0.9em;color:#4a5568;">{warn_text}</td>
                </tr>"""
            )

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Split & Stitch Motion Quality Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2rem; background: #f7fafc; color: #2d3748; }}
.card {{ background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 1.5rem; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #edf2f7; font-weight: 600; }}
.summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }}
.metric-box {{ background: #edf2f7; padding: 1rem; border-radius: 6px; text-align: center; }}
.metric-value {{ font-size: 1.5rem; font-weight: bold; color: #2b6cb0; }}
</style>
</head>
<body>
<h1>Motion Stitch Quality Report</h1>
<div class="card summary-grid">
  <div class="metric-box">
    <div>Total Duration</div>
    <div class="metric-value">{self.total_duration_sec:.2f}s</div>
  </div>
  <div class="metric-box">
    <div>Total Frames</div>
    <div class="metric-value">{self.total_frames}</div>
  </div>
  <div class="metric-box">
    <div>Seams Evaluated</div>
    <div class="metric-value">{self.total_seams}</div>
  </div>
  <div class="metric-box">
    <div>Overall Status</div>
    <div class="metric-value" style="color: {'#e53e3e' if self.overall_status != 'clean' else '#38a169'};">{self.overall_status.upper()}</div>
  </div>
</div>

<div class="card">
  <h2>Seam Boundary Diagnostics</h2>
  <table>
    <thead>
      <tr>
        <th>Seam</th>
        <th>Status</th>
        <th>Mean Angle Diff</th>
        <th>Yaw Correction</th>
        <th>Translation Offset</th>
        <th>Estimated Lag</th>
        <th>Accel Spike</th>
        <th>Diagnostic Notes</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</div>
</body>
</html>"""
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)


def evaluate_seam_qc(
    seam_index: int,
    chunk_a_idx: int,
    chunk_b_idx: int,
    mean_angle_rad: float,
    max_angle_rad: float,
    yaw_deg: float,
    offset_xyz: np.ndarray,
    temporal_lag: int,
    accel_spike_ratio: float,
) -> SeamQCMetrics:
    """Evaluate quality thresholds for a single seam."""
    mean_deg = float(np.degrees(mean_angle_rad))
    max_deg = float(np.degrees(max_angle_rad))
    trans_norm = float(np.linalg.norm(offset_xyz))

    warnings: List[str] = []
    if mean_deg > 15.0:
        warnings.append(f"High pose difference ({mean_deg:.1f}° > 15°)")
    if abs(yaw_deg) > 30.0:
        warnings.append(f"Large Yaw correction ({yaw_deg:.1f}° > 30°)")
    if trans_norm > 0.5:
        warnings.append(f"Significant horizontal offset ({trans_norm:.2f}m > 0.5m)")
    if temporal_lag != 0:
        warnings.append(f"Detected temporal frame lag ({temporal_lag:+d} frames)")
    if accel_spike_ratio > 3.0:
        warnings.append(f"Acceleration spike at seam ({accel_spike_ratio:.1f}x > 3.0x)")

    return SeamQCMetrics(
        seam_index=seam_index,
        chunk_a_index=chunk_a_idx,
        chunk_b_index=chunk_b_idx,
        mean_angle_diff_deg=round(mean_deg, 3),
        max_angle_diff_deg=round(max_deg, 3),
        yaw_correction_deg=round(yaw_deg, 3),
        translation_correction_m=round(trans_norm, 4),
        temporal_lag=temporal_lag,
        accel_spike_ratio=round(accel_spike_ratio, 2),
        has_warning=len(warnings) > 0,
        warnings=warnings,
    )
