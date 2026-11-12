"""MurmurHash3, and the field-ID derivation used by the save container.

Every key in a save file is stored as a 32-bit hash of its name.  The game
builds names like ``PlayerStatus.DiveDepth`` or ``PouchData.Item_Scale_Gold.StockNum``
and hashes the UTF-8 bytes with MurmurHash3 (x86, 32-bit, seed 0).

Verified against 1,939 of 1,953 names published by the community save editor;
the 14 misses are all ``<Dungeon>.SmallKeyNum`` and are carried verbatim in
``ootsw2/data/fields.json`` as unverified aliases.

Knowing the derivation matters: it turns "guess a 32-bit id" into
"write down the name", which is what makes ``probe`` and ``diff`` useful.
"""

from __future__ import annotations

__all__ = ["murmur3_32", "field_id", "MAX_FIELD_ID"]

MAX_FIELD_ID = 0xFFFFFFFF

_C1 = 0xCC9E2D51
_C2 = 0x1B873593
_M32 = 0xFFFFFFFF


def _rotl32(x: int, r: int) -> int:
    return ((x << r) | (x >> (32 - r))) & _M32


def murmur3_32(data: bytes, seed: int = 0) -> int:
    """MurmurHash3 x86 32-bit, seed 0 by default."""
    length = len(data)
    h = seed & _M32
    i = 0

    while i + 4 <= length:
        k = int.from_bytes(data[i:i + 4], "little")
        k = (k * _C1) & _M32
        k = _rotl32(k, 15)
        k = (k * _C2) & _M32
        h ^= k
        h = _rotl32(h, 13)
        h = (h * 5 + 0xE6546B64) & _M32
        i += 4

    tail = data[i:]
    k = 0
    if len(tail) >= 3:
        k ^= tail[2] << 16
    if len(tail) >= 2:
        k ^= tail[1] << 8
    if len(tail) >= 1:
        k ^= tail[0]
        k = (k * _C1) & _M32
        k = _rotl32(k, 15)
        k = (k * _C2) & _M32
        h ^= k

    h ^= length
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & _M32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & _M32
    h ^= h >> 16
    return h


def field_id(name: str) -> int:
    """Derive the on-disk key for a field name.

    >>> field_id("PlayerStatus.DiveDepth")
    1632005153
    >>> field_id("PouchData.Item_Scale_Gold.StockNum")
    1256920074
    """
    if not isinstance(name, str):
        raise TypeError("field name must be str")
    if not name:
        raise ValueError("field name must not be empty")
    return murmur3_32(name.encode("utf-8"))
