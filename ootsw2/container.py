"""Reader/writer for the save container used by Ocarina of Time (Switch 2).

Every save file in the save directory -- ``progress.sav``, ``caption.sav``,
``option.sav``, ``account.sav`` -- uses the same container:

    offset 0    u32   magic   0x01020304
    offset 4    u32   version 0x002D80EB
    offset 8    u32   header_end  (end of the key/value table)
    offset 12   ..    reserved, zero
    offset 40   header_end        entries of 8 bytes: [u32 key][u32 value]
    header_end  EOF               typed payload: fixed-size records

A ``value`` is either an inline scalar or an offset into the payload where a
fixed-size record lives: a NUL-padded string in a 64-byte slot, a 12-byte
vector, or an array (a count followed by fixed-size elements).  There is no
checksum and no type tag, so a field can be rewritten in place without touching
anything else.

See ``docs/FORMAT.md`` for the full description and how it was derived.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from .hash import field_id

__all__ = [
    "MAGIC",
    "VERSION",
    "HEADER_SIZE",
    "SaveFormatError",
    "SaveFile",
    "SaveDiff",
    "is_inline_scalar",
]

MAGIC = 0x01020304
VERSION = 0x002D80EB
HEADER_SIZE = 40
ENTRY_SIZE = 8

_MAX_STRING_LEN = 96
# Game identifiers in the pool are all long ("Weapon_Sword_Master",
# "HyruleField", "Goto_HyruleCastle").  A one- or two-character "string" is
# always an integer array whose bytes happen to be printable: a field holding
# 167280 used to come back as "V" (0x56), because that value lands inside the
# payload and the byte there is 0x56.  The shortest real entry measured across
# six slots is 11 characters, so four is a safe floor.
_MIN_STRING_LEN = 4


class SaveFormatError(ValueError):
    """Raised when a file does not look like a save container."""


def _looks_like_string(blob: bytes, offset: int) -> Optional[str]:
    """Return the string at ``offset`` if it is a plausible pool entry."""
    if offset < 0 or offset >= len(blob):
        return None
    end = blob.find(b"\x00", offset, offset + _MAX_STRING_LEN)
    if end <= offset:
        return None
    raw = blob[offset:end]
    if len(raw) < _MIN_STRING_LEN:
        return None
    # Pool entries are game identifiers: printable ASCII starting uppercase.
    if not (0x41 <= raw[0] <= 0x5A):
        return None
    for byte in raw:
        if not (0x20 <= byte < 0x7F):
            return None
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:  # pragma: no cover - guarded above
        return None


def is_inline_scalar(blob: bytes, header_end: int, value: int) -> bool:
    """True when ``value`` should be read as a number rather than a pool offset."""
    if value < header_end or value >= len(blob):
        return True
    return _looks_like_string(blob, value) is None


@dataclass(frozen=True)
class SaveDiff:
    """One changed / added / removed field between two saves."""

    field_id: int
    name: Optional[str]
    before: Optional[int]
    after: Optional[int]

    @property
    def kind(self) -> str:
        if self.before is None:
            return "added"
        if self.after is None:
            return "removed"
        return "changed"


class SaveFile:
    """A single ``*.sav`` file, parsed in memory.

    The original bytes are kept verbatim; edits patch the value words in place,
    so an untouched field is a byte-for-byte copy of the input.
    """

    def __init__(self, path: str, data: Optional[bytes] = None) -> None:
        self.path = path
        self.name = os.path.basename(path)
        raw = data if data is not None else open(path, "rb").read()
        if len(raw) < HEADER_SIZE:
            raise SaveFormatError(f"{self.name}: file too short ({len(raw)} bytes)")

        magic, version, header_end = struct.unpack_from("<III", raw, 0)
        if magic != MAGIC:
            raise SaveFormatError(
                f"{self.name}: bad magic 0x{magic:08X}, expected 0x{MAGIC:08X}"
            )
        if version != VERSION:
            raise SaveFormatError(
                f"{self.name}: unsupported version 0x{version:08X}, "
                f"expected 0x{VERSION:08X}"
            )
        if header_end < HEADER_SIZE or header_end > len(raw) or (header_end - HEADER_SIZE) % ENTRY_SIZE:
            raise SaveFormatError(
                f"{self.name}: header_end 0x{header_end:X} is not a valid table boundary"
            )

        self.data = bytearray(raw)
        self.version = version
        self.header_end = header_end

        # field id -> byte offset of its 4-byte value word
        self._slots: Dict[int, int] = {}
        # free table slots (key == 0), as offsets of the key word
        self._free: List[int] = []
        for offset in range(HEADER_SIZE, header_end, ENTRY_SIZE):
            key = struct.unpack_from("<I", self.data, offset)[0]
            if key == 0:
                self._free.append(offset)
            elif key not in self._slots:
                self._slots[key] = offset + 4

    # ------------------------------------------------------------------ basics

    def __len__(self) -> int:
        return len(self._slots)

    def __contains__(self, field: object) -> bool:
        return self._resolve(field) in self._slots

    def __iter__(self) -> Iterator[int]:
        return iter(sorted(self._slots))

    @property
    def payload_start(self) -> int:
        return self.header_end

    @property
    def free_slots(self) -> int:
        """How many empty table entries are left for adding new fields."""
        return len(self._free)

    def _resolve(self, field: object) -> int:
        if isinstance(field, str):
            return field_id(field)
        if isinstance(field, int):
            return field & 0xFFFFFFFF
        raise TypeError("field must be a name (str) or a numeric id (int)")

    # -------------------------------------------------------------- read side

    def get_raw(self, field: object) -> Optional[int]:
        """The stored 32-bit word, or ``None`` when the field is absent."""
        offset = self._slots.get(self._resolve(field))
        if offset is None:
            return None
        return struct.unpack_from("<I", self.data, offset)[0]

    def get_int(self, field: object, *, signed: bool = False) -> Optional[int]:
        offset = self._slots.get(self._resolve(field))
        if offset is None:
            return None
        return struct.unpack_from("<i" if signed else "<I", self.data, offset)[0]

    def get_float(self, field: object) -> Optional[float]:
        offset = self._slots.get(self._resolve(field))
        if offset is None:
            return None
        return struct.unpack_from("<f", self.data, offset)[0]

    def get_str(self, field: object) -> Optional[str]:
        """Read a string field from the payload pool, or ``None``."""
        value = self.get_raw(field)
        if value is None:
            return None
        if is_inline_scalar(self.data, self.header_end, value):
            return None
        return _looks_like_string(self.data, value)

    def is_string(self, field: object) -> bool:
        return self.get_str(field) is not None

    def items(self) -> Iterator[Tuple[int, int]]:
        """Iterate ``(field_id, raw_value)`` in ascending field-id order."""
        for fid in sorted(self._slots):
            yield fid, self.get_raw(fid)

    # ------------------------------------------------------------- write side

    def set_raw(self, field: object, value: int) -> Optional[int]:
        """Overwrite a field's 32-bit word. Returns the previous value."""
        fid = self._resolve(field)
        offset = self._slots.get(fid)
        if offset is None:
            raise KeyError(f"field {field!r} (id {fid}) is not present in {self.name}")
        previous = struct.unpack_from("<I", self.data, offset)[0]
        struct.pack_into("<I", self.data, offset, value & 0xFFFFFFFF)
        return previous

    def set_int(self, field: object, value: int, *, signed: bool = False) -> Optional[int]:
        fmt = "<i" if signed else "<I"
        max_value = (1 << (31 if signed else 32)) - 1
        min_value = -(1 << 31) if signed else 0
        if not (min_value <= value <= max_value):
            raise ValueError(f"{value} does not fit in a {'signed' if signed else 'unsigned'} 32-bit word")
        return self.set_raw(field, struct.unpack("<I", struct.pack(fmt, value))[0])

    def set_float(self, field: object, value: float) -> Optional[int]:
        return self.set_raw(field, struct.unpack("<I", struct.pack("<f", value))[0])

    def set_str(self, field: object, text: str) -> Optional[int]:
        """Write a string field.

        If the existing string is at least as long as the new one, it is
        overwritten in place.  Otherwise the new text is appended to the
        payload and the field is re-pointed at it; the file grows by a few
        bytes, which is exactly what the game itself does when it saves.
        """
        if not text or "\x00" in text:
            raise ValueError("string value must be non-empty and must not contain NUL")
        encoded = text.encode("ascii")
        fid = self._resolve(field)
        offset = self._slots.get(fid)
        if offset is None:
            raise KeyError(f"field {field!r} (id {fid}) is not present in {self.name}")

        previous = struct.unpack_from("<I", self.data, offset)[0]
        if not is_inline_scalar(self.data, self.header_end, previous):
            end = self.data.find(b"\x00", previous, previous + _MAX_STRING_LEN)
            if end > previous and (end - previous) >= len(encoded):
                self.data[previous:previous + len(encoded)] = encoded
                self.data[previous + len(encoded)] = 0
                for i in range(previous + len(encoded) + 1, end):
                    self.data[i] = 0
                return previous

        new_offset = len(self.data)
        self.data.extend(encoded)
        self.data.append(0)
        struct.pack_into("<I", self.data, offset, new_offset)
        return previous

    def add(self, field: object, value: int) -> None:
        """Insert a field that is not present yet, using a spare table slot."""
        fid = self._resolve(field)
        if fid in self._slots:
            raise KeyError(f"field {field!r} (id {fid}) already present in {self.name}")
        if not self._free:
            raise SaveFormatError(f"{self.name}: no free table slots left")
        offset = self._free.pop(0)
        struct.pack_into("<II", self.data, offset, fid, value & 0xFFFFFFFF)
        self._slots[fid] = offset + 4

    def remove(self, field: object) -> None:
        """Clear a field by zeroing its key, freeing the table slot."""
        fid = self._resolve(field)
        offset = self._slots.pop(fid, None)
        if offset is None:
            raise KeyError(f"field {field!r} (id {fid}) is not present in {self.name}")
        struct.pack_into("<II", self.data, offset - 4, 0, 0)
        self._free.append(offset - 4)
        self._free.sort()

    # ------------------------------------------------------------------ output

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path
        tmp = target + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(self.data)
        os.replace(tmp, target)
        return target

    # -------------------------------------------------------------------- diff

    def diff(self, other: "SaveFile", names: Optional[Dict[int, str]] = None) -> List[SaveDiff]:
        """Field-level differences from ``self`` (before) to ``other`` (after)."""
        names = names or {}
        changes: List[SaveDiff] = []
        for fid in sorted(set(self._slots) | set(other._slots)):
            before = self.get_raw(fid)
            after = other.get_raw(fid)
            if before == after:
                continue
            changes.append(SaveDiff(fid, names.get(fid), before, after))
        return changes

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"<SaveFile {self.name} fields={len(self._slots)} "
            f"header_end=0x{self.header_end:X} size={len(self.data)}>"
        )
