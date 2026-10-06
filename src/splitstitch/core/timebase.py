"""Rational timebase and timeline representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Sequence
import numpy as np


def parse_fraction(value: str | float | int | Fraction) -> Fraction:
    """Parse string or numeric to Fraction with strict handling."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, float):
        # Limit denominator to avoid extreme fractions from floats
        return Fraction(value).limit_denominator(120000)
    if isinstance(value, str):
        val = value.strip()
        if "/" in val:
            num, den = val.split("/", 1)
            return Fraction(int(num.strip()), int(den.strip()))
        if "." in val:
            return Fraction(float(val)).limit_denominator(120000)
        return Fraction(int(val), 1)
    raise ValueError(f"Cannot parse {value!r} into Fraction")


def format_fraction(frac: Fraction) -> str:
    """Format Fraction to 'num/den' or 'num'."""
    if frac.denominator == 1:
        return f"{frac.numerator}/1"
    return f"{frac.numerator}/{frac.denominator}"


@dataclass(frozen=True)
class TimeBase:
    """Represents a discrete sampling timebase with rational FPS."""

    fps: Fraction

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError(f"FPS must be positive, got {self.fps}")

    @classmethod
    def from_fps(cls, fps: str | float | int | Fraction) -> TimeBase:
        return cls(fps=parse_fraction(fps))

    @property
    def frame_duration_sec(self) -> float:
        return float(1 / self.fps)

    def frame_to_time(self, frame_idx: int | float) -> float:
        return float(frame_idx / self.fps)

    def time_to_frame(self, time_sec: float) -> int:
        return int(round(time_sec * float(self.fps)))

    def __str__(self) -> str:
        return format_fraction(self.fps)


@dataclass
class FrameTimeline:
    """CFR or VFR timeline mapping frame indices to precise timestamps."""

    pts_seconds: np.ndarray  # shape (N,)
    nominal_fps: Fraction
    is_vfr: bool = False

    @classmethod
    def create_cfr(cls, frame_count: int, fps: Fraction, start_pts: float = 0.0) -> FrameTimeline:
        step = float(1 / fps)
        pts = start_pts + np.arange(frame_count, dtype=np.float64) * step
        return cls(pts_seconds=pts, nominal_fps=fps, is_vfr=False)

    @classmethod
    def create_vfr(cls, pts_seconds: Sequence[float], nominal_fps: Fraction | None = None) -> FrameTimeline:
        pts = np.asarray(pts_seconds, dtype=np.float64)
        if len(pts) < 2:
            nom = nominal_fps or Fraction(30, 1)
            return cls(pts_seconds=pts, nominal_fps=nom, is_vfr=False)

        diffs = np.diff(pts)
        median_dt = float(np.median(diffs))
        auto_fps = Fraction(1.0 / median_dt).limit_denominator(120000) if median_dt > 0 else Fraction(30, 1)
        nom = nominal_fps or auto_fps

        # Check if actually VFR (> 1% variance from median dt)
        if median_dt > 0:
            max_dev = np.max(np.abs(diffs - median_dt)) / median_dt
            is_vfr = bool(max_dev > 0.01)
        else:
            is_vfr = False

        return cls(pts_seconds=pts, nominal_fps=nom, is_vfr=is_vfr)

    def __len__(self) -> int:
        return len(self.pts_seconds)

    def get_time(self, frame_idx: int | float) -> float:
        """Get timestamp in seconds for a possibly fractional frame index."""
        if len(self.pts_seconds) == 0:
            return 0.0
        if not self.is_vfr:
            step = float(1 / self.nominal_fps)
            return float(self.pts_seconds[0] + frame_idx * step)

        # For VFR: linear interpolation on pts_seconds
        idx_clamped = np.clip(frame_idx, 0, len(self.pts_seconds) - 1)
        return float(np.interp(idx_clamped, np.arange(len(self.pts_seconds)), self.pts_seconds))

    def time_to_frame(self, time_sec: float) -> float:
        """Inverse mapping: timestamp to continuous frame index."""
        if len(self.pts_seconds) == 0:
            return 0.0
        if not self.is_vfr:
            step = float(1 / self.nominal_fps)
            return float((time_sec - self.pts_seconds[0]) / step)
        return float(np.interp(time_sec, self.pts_seconds, np.arange(len(self.pts_seconds))))
