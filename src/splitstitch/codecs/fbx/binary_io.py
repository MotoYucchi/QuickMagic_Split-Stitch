"""Binary FBX node parser and serializer."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union


@dataclass
class FBXProperty:
    type_code: str
    value: Any


@dataclass
class FBXNode:
    name: str
    properties: List[FBXProperty] = field(default_factory=list)
    children: List[FBXNode] = field(default_factory=list)

    def find_child(self, name: str) -> Optional[FBXNode]:
        for c in self.children:
            if c.name == name:
                return c
        return None

    def find_children(self, name: str) -> List[FBXNode]:
        return [c for c in self.children if c.name == name]


FBX_HEADER_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
KTIME_PER_SECOND = 46_186_158_000


def parse_binary_fbx(data: bytes) -> Tuple[int, List[FBXNode]]:
    """Parse binary FBX buffer into version and top-level node list."""
    if not data.startswith(FBX_HEADER_MAGIC):
        raise ValueError("Not a valid binary FBX file: invalid magic header")

    (version,) = struct.unpack_from("<I", data, 23)
    is_64bit = version >= 7500

    offset = 27
    nodes: List[FBXNode] = []

    while offset < len(data):
        node, offset = _read_node(data, offset, is_64bit)
        if node is None:
            # Reached null sentinel or end
            break
        nodes.append(node)

    return version, nodes


def _read_node(data: bytes, offset: int, is_64bit: bool) -> Tuple[Optional[FBXNode], int]:
    if is_64bit:
        if offset + 25 > len(data):
            return None, len(data)
        end_offset, num_props, prop_len, name_len = struct.unpack_from("<QQQB", data, offset)
        header_len = 25
    else:
        if offset + 13 > len(data):
            return None, len(data)
        end_offset, num_props, prop_len, name_len = struct.unpack_from("<IIIB", data, offset)
        header_len = 13

    # Null sentinel indicating end of children or end of document
    if end_offset == 0 and num_props == 0 and prop_len == 0 and name_len == 0:
        return None, offset + header_len

    name = data[offset + header_len : offset + header_len + name_len].decode("utf-8", errors="replace")
    prop_offset = offset + header_len + name_len

    properties: List[FBXProperty] = []
    for _ in range(num_props):
        prop, prop_offset = _read_property(data, prop_offset)
        properties.append(prop)

    children: List[FBXNode] = []
    child_offset = prop_offset

    while child_offset < end_offset:
        child, next_off = _read_node(data, child_offset, is_64bit)
        if child is None:
            child_offset = next_off
            break
        children.append(child)
        child_offset = next_off

    return FBXNode(name=name, properties=properties, children=children), end_offset


def _read_property(data: bytes, offset: int) -> Tuple[FBXProperty, int]:
    type_code = chr(data[offset])
    offset += 1

    if type_code == "Y":  # int16
        val, = struct.unpack_from("<h", data, offset)
        return FBXProperty(type_code, val), offset + 2
    elif type_code == "C":  # bool (1 byte)
        val, = struct.unpack_from("<?", data, offset)
        return FBXProperty(type_code, val), offset + 1
    elif type_code == "I":  # int32
        val, = struct.unpack_from("<i", data, offset)
        return FBXProperty(type_code, val), offset + 4
    elif type_code == "F":  # float32
        val, = struct.unpack_from("<f", data, offset)
        return FBXProperty(type_code, val), offset + 4
    elif type_code == "D":  # double (float64)
        val, = struct.unpack_from("<d", data, offset)
        return FBXProperty(type_code, val), offset + 8
    elif type_code == "L":  # int64
        val, = struct.unpack_from("<q", data, offset)
        return FBXProperty(type_code, val), offset + 8
    elif type_code in ("S", "R"):  # String or Raw binary
        length, = struct.unpack_from("<I", data, offset)
        offset += 4
        val = data[offset : offset + length]
        return FBXProperty(type_code, val), offset + length

    # Array types: 'b', 'c', 'i', 'f', 'd', 'l'
    elif type_code in ("b", "c", "i", "f", "d", "l"):
        array_len, encoding, comp_len = struct.unpack_from("<III", data, offset)
        offset += 12

        arr_bytes = data[offset : offset + comp_len]
        offset += comp_len

        if encoding == 1:
            arr_bytes = zlib.decompress(arr_bytes)

        fmt_map = {
            "b": "<?", "c": "<?",
            "i": "<i", "f": "<f",
            "d": "<d", "l": "<q",
        }
        item_fmt = fmt_map[type_code]
        item_size = struct.calcsize(item_fmt)
        parsed_array = [
            struct.unpack_from(item_fmt, arr_bytes, i * item_size)[0]
            for i in range(array_len)
        ]
        return FBXProperty(type_code, parsed_array), offset

    raise ValueError(f"Unknown FBX property type code: '{type_code}' at offset {offset-1}")


def write_binary_fbx(version: int, nodes: List[FBXNode]) -> bytes:
    """Serialize FBX nodes into binary FBX buffer."""
    is_64bit = version >= 7500
    out = bytearray(FBX_HEADER_MAGIC)
    out.extend(struct.pack("<I", version))

    for node in nodes:
        _write_node(out, node, is_64bit)

    # File footer: null sentinel (header_len zeros) + footer magic
    footer_len = 25 if is_64bit else 13
    out.extend(b"\x00" * footer_len)
    return bytes(out)


def _write_node(buf: bytearray, node: FBXNode, is_64bit: bool) -> None:
    start_offset = len(buf)
    header_len = 25 if is_64bit else 13

    # Placeholder for header
    buf.extend(b"\x00" * header_len)

    name_bytes = node.name.encode("utf-8")
    buf.extend(name_bytes)

    prop_start = len(buf)
    for prop in node.properties:
        _write_property(buf, prop)
    prop_len = len(buf) - prop_start

    for child in node.children:
        _write_node(buf, child, is_64bit)

    if node.children:
        # Children end with null sentinel
        buf.extend(b"\x00" * header_len)

    end_offset = len(buf)

    # Patch header
    if is_64bit:
        header_data = struct.pack("<QQQB", end_offset, len(node.properties), prop_len, len(name_bytes))
    else:
        header_data = struct.pack("<IIIB", end_offset, len(node.properties), prop_len, len(name_bytes))

    buf[start_offset : start_offset + header_len] = header_data


def _write_property(buf: bytearray, prop: FBXProperty) -> None:
    t = prop.type_code
    buf.append(ord(t))

    if t == "Y":
        buf.extend(struct.pack("<h", prop.value))
    elif t == "C":
        buf.extend(struct.pack("<?", prop.value))
    elif t == "I":
        buf.extend(struct.pack("<i", prop.value))
    elif t == "F":
        buf.extend(struct.pack("<f", prop.value))
    elif t == "D":
        buf.extend(struct.pack("<d", prop.value))
    elif t == "L":
        buf.extend(struct.pack("<q", prop.value))
    elif t in ("S", "R"):
        val_bytes = prop.value if isinstance(prop.value, bytes) else str(prop.value).encode("utf-8")
        buf.extend(struct.pack("<I", len(val_bytes)))
        buf.extend(val_bytes)
    elif t in ("b", "c", "i", "f", "d", "l"):
        fmt_map = {"b": "<?", "c": "<?", "i": "<i", "f": "<f", "d": "<d", "l": "<q"}
        item_fmt = fmt_map[t]
        raw_items = bytearray()
        for v in prop.value:
            raw_items.extend(struct.pack(item_fmt, v))

        # Check if compressing array
        if len(raw_items) > 128:
            comp_bytes = zlib.compress(bytes(raw_items), level=6)
            buf.extend(struct.pack("<III", len(prop.value), 1, len(comp_bytes)))
            buf.extend(comp_bytes)
        else:
            buf.extend(struct.pack("<III", len(prop.value), 0, len(raw_items)))
            buf.extend(raw_items)
