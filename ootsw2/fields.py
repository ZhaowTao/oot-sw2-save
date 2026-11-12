"""The field-name dictionary.

Because a field's key is ``murmur3_32(name)``, the only thing worth shipping is
the *list of names*.  ``data/fields.json`` maps each known name to the id it was
observed with, which makes the file self-checking: for every entry except a
handful of legacy aliases, ``field_id(name) == id``.

Provenance
----------
* 1,939 names cross-checked against the community editor's published table
  (``Traiver/OOT-SW2SE``, MIT).  Every one of them satisfies the hash relation,
  which is what proved the derivation in the first place.
* 7 names recovered here by probing the hash against live save data
  (``PlayerStatus.EquipHandArmor``, ``LiftGrade``, ``IsDefenseUP``, ...).
* 14 ``<Dungeon>.SmallKeyNum`` entries keep the id observed on disk because
  they do *not* satisfy the hash relation.  They are marked by
  :meth:`FieldDictionary.unverified`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .hash import field_id

__all__ = ["FieldDictionary", "DICTIONARY", "resolve_field"]

_DATA = os.path.join(os.path.dirname(__file__), "data", "fields.json")


class FieldDictionary:
    """Name <-> id mapping with search and self-verification."""

    def __init__(self, mapping: Dict[str, int]) -> None:
        self._by_name: Dict[str, int] = dict(mapping)
        self._by_id: Dict[int, str] = {}
        for name, fid in sorted(self._by_name.items()):
            self._by_id.setdefault(fid, name)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "FieldDictionary":
        with open(path or _DATA, "r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __iter__(self) -> Iterable[str]:
        return iter(sorted(self._by_name))

    def id_of(self, name: str) -> Optional[int]:
        return self._by_name.get(name)

    def name_of(self, fid: int) -> Optional[str]:
        return self._by_id.get(fid)

    def names(self) -> List[str]:
        return sorted(self._by_name)

    def id_map(self) -> Dict[int, str]:
        """Copy of the id -> name mapping, for diffing and reporting."""
        return dict(self._by_id)

    def search(self, pattern: str, *, regex: bool = False) -> List[str]:
        """Case-insensitive substring search, or a regex when ``regex`` is set."""
        if regex:
            compiled = re.compile(pattern, re.IGNORECASE)
            return [n for n in self.names() if compiled.search(n)]
        needle = pattern.lower()
        return [n for n in self.names() if needle in n.lower()]

    def unverified(self) -> List[Tuple[str, int, int]]:
        """Entries whose stored id disagrees with ``murmur3_32(name)``."""
        bad: List[Tuple[str, int, int]] = []
        for name, fid in sorted(self._by_name.items()):
            computed = field_id(name)
            if computed != fid:
                bad.append((name, fid, computed))
        return bad

    def with_prefix(self, prefix: str) -> List[str]:
        return [n for n in self.names() if n.startswith(prefix)]


DICTIONARY = FieldDictionary.load()


def resolve_field(field: object) -> Tuple[int, Optional[str]]:
    """Turn a user-supplied field reference into ``(id, known_name_or_None)``.

    Accepts a full name (``PlayerStatus.DiveDepth``), a decimal id
    (``1632005153``), or a ``0x``-prefixed hex id.
    """
    if isinstance(field, int):
        return field & 0xFFFFFFFF, DICTIONARY.name_of(field & 0xFFFFFFFF)
    if not isinstance(field, str):
        raise TypeError("field reference must be a name string or a numeric id")

    text = field.strip()
    if not text:
        raise ValueError("empty field reference")

    known = DICTIONARY.id_of(text)
    if known is not None:
        return known, text

    if text.lower().startswith("0x"):
        raw = int(text, 16)
    elif text.isdigit():
        raw = int(text, 10)
    else:
        # Not in the dictionary but still a legal name: derive it.
        return field_id(text), text
    return raw & 0xFFFFFFFF, DICTIONARY.name_of(raw & 0xFFFFFFFF)
