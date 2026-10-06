"""Codec registry and automatic format detection."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Type

from splitstitch.codecs.base import BaseCodec
from splitstitch.codecs.bvh import BVHCodec
from splitstitch.codecs.fbx.fbx_codec import FBXCodec
from splitstitch.codecs.vmd import VMDCodec

CODEC_REGISTRY: Dict[str, Type[BaseCodec]] = {
    "bvh": BVHCodec,
    "fbx": FBXCodec,
    "vmd": VMDCodec,
}


def get_codec_for_file(path: Path | str) -> BaseCodec:
    """Detect and instantiate appropriate codec based on file extension."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in CODEC_REGISTRY:
        raise ValueError(
            f"Unsupported motion format: '.{ext}'. Supported: {list(CODEC_REGISTRY.keys())}"
        )
    return CODEC_REGISTRY[ext]()


def get_codec_by_name(format_name: str) -> BaseCodec:
    """Instantiate codec by name."""
    fmt = format_name.lower().strip()
    if fmt not in CODEC_REGISTRY:
        raise ValueError(
            f"Unknown format name: '{format_name}'. Supported: {list(CODEC_REGISTRY.keys())}"
        )
    return CODEC_REGISTRY[fmt]()
