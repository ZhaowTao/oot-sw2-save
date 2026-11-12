"""Read and edit save files from The Legend of Zelda: Ocarina of Time (Switch 2).

Quick start::

    >>> from ootsw2 import SaveFile, field_id
    >>> save = SaveFile("progress.sav")          # doctest: +SKIP
    >>> save.get_int("PlayerStatus.CurrentRupee")  # doctest: +SKIP
    666
    >>> field_id("PlayerStatus.DiveDepth")
    1632005153
"""

from __future__ import annotations

from .container import MAGIC, VERSION, SaveDiff, SaveFile, SaveFormatError, is_inline_scalar
from .fields import DICTIONARY, FieldDictionary, resolve_field
from .hash import field_id, murmur3_32
from .savedir import SaveDirectory, SlotInfo, find_title_dirs

__version__ = "0.1.0"

__all__ = [
    "DICTIONARY",
    "MAGIC",
    "VERSION",
    "FieldDictionary",
    "SaveDiff",
    "SaveDirectory",
    "SaveFile",
    "SaveFormatError",
    "SlotInfo",
    "__version__",
    "field_id",
    "find_title_dirs",
    "is_inline_scalar",
    "murmur3_32",
    "resolve_field",
]
