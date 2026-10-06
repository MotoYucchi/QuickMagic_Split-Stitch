"""Unit tests for timebase and timeline."""

from fractions import Fraction
import numpy as np
import pytest

from splitstitch.core.timebase import FrameTimeline, TimeBase, format_fraction, parse_fraction


def test_parse_fraction() -> None:
    assert parse_fraction("30") == Fraction(30, 1)
    assert parse_fraction("30/1") == Fraction(30, 1)
    assert parse_fraction("60000/1001") == Fraction(60000, 1001)
    assert parse_fraction(60) == Fraction(60, 1)
    assert parse_fraction(59.94) == Fraction(59.94).limit_denominator(120000)
    assert parse_fraction(Fraction(24, 1)) == Fraction(24, 1)

    with pytest.raises(ValueError):
        parse_fraction("invalid")


def test_format_fraction() -> None:
    assert format_fraction(Fraction(30, 1)) == "30/1"
    assert format_fraction(Fraction(60000, 1001)) == "60000/1001"


def test_timebase_math() -> None:
    tb = TimeBase.from_fps("60/1")
    assert tb.frame_duration_sec == pytest.approx(1.0 / 60.0)
    assert tb.frame_to_time(120) == pytest.approx(2.0)
    assert tb.time_to_frame(2.0) == 120


def test_cfr_timeline() -> None:
    tl = FrameTimeline.create_cfr(frame_count=100, fps=Fraction(30, 1), start_pts=0.0)
    assert len(tl) == 100
    assert not tl.is_vfr
    assert tl.get_time(0) == pytest.approx(0.0)
    assert tl.get_time(30) == pytest.approx(1.0)
    assert tl.time_to_frame(1.0) == pytest.approx(30.0)


def test_vfr_timeline() -> None:
    # Slightly irregular timestamps
    pts = [0.0, 0.033, 0.068, 0.105, 0.140]
    tl = FrameTimeline.create_vfr(pts)
    assert len(tl) == 5
    assert tl.is_vfr
    t2 = tl.get_time(2)
    assert t2 == pytest.approx(0.068)
    f2 = tl.time_to_frame(0.068)
    assert f2 == pytest.approx(2.0)
