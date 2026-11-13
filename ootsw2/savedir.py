"""The save *directory*, which is where most edits go wrong.

A single ``progress.sav`` is not the whole picture.  On disk the game keeps six
rotating slots::

    <title-id>/
        save/
            account.sav
            option.sav
            slot_00/{progress.sav,caption.sav}
            ...
            slot_05/{progress.sav,caption.sav}
        save.work/          <- what the engine actually mounts while running
        env.txt

``caption.sav`` is the file the Load screen draws from: the location, the game's
own save clock, an autosave/manual flag, and a 543×306 JPEG thumbnail.  It is
read here so a listing can show what the game will show, instead of guessing
from file mtimes.

Three facts, each of which silently breaks an edit if you get it wrong:

1. **The game writes to a different slot every time it saves.**  It does not
   round-robin strictly, but it does move.  Loading picks the newest slot, so
   editing only ``slot_05`` when the game will load ``slot_02`` looks exactly
   like "the edit did nothing".
2. **The engine mounts ``save.work``, not ``save``** while the game runs, and
   swaps it back over ``save`` on commit.  Editing ``save/`` alone can be
   overwritten wholesale.
3. **Edits are lost if the game is running.**  On exit it flushes the in-memory
   state over whatever is on disk.

This module exists so callers edit *all* slots and *both* directories in one go,
and can tell whether the game is still running before touching anything.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .container import SaveFile

__all__ = ["SlotInfo", "Caption", "SaveDirectory", "find_title_dirs", "read_caption"]

PROGRESS = "progress.sav"
CAPTION = "caption.sav"

# caption.sav describes one slot for the Load screen: where it was saved, when,
# whether it was an autosave, and a 543x306 JPEG thumbnail.
CAPTION_POS = 0x8B26618E
CAPTION_LOCATION = 0xF74E0E8E
CAPTION_STAGE_PATH = 0x0CCCC6CD
CAPTION_AUTOSAVE = 0x25F03CAA
CAPTION_TIME = (0x9811A3F7, 0xDFD840D3, 0xBD46F485, 0x23F3D75E, 0x27853BF7)
_JPEG_SOI = b"\xff\xd8\xff"


@dataclass
class Caption:
    """What the Load screen shows for one slot."""

    saved_at: Optional[str] = None          # "2026-11-13 13:23", game's own clock
    location: Optional[str] = None
    stage_path: Optional[str] = None
    autosave: Optional[bool] = None
    thumbnail: Optional[tuple] = None       # (width, height) of the embedded JPEG

    @property
    def kind(self) -> str:
        if self.autosave is None:
            return "-"
        return "auto" if self.autosave else "manual"


def _jpeg_size(blob: bytes, start: int) -> Optional[tuple]:
    """Width and height from the first SOF marker after ``start``."""
    i = start + 2
    while i < len(blob) - 9:
        if blob[i] != 0xFF:
            return None
        marker = blob[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(blob[i + 5:i + 7], "big")
            width = int.from_bytes(blob[i + 7:i + 9], "big")
            return (width, height)
        i += 2 + int.from_bytes(blob[i + 2:i + 4], "big")
    return None


def read_caption(path: str) -> Optional[Caption]:
    """Parse a ``caption.sav``, or return ``None`` when it cannot be read."""
    if not os.path.isfile(path):
        return None
    try:
        save = SaveFile(path)
    except (OSError, ValueError):
        return None

    caption = Caption()
    caption.location = save.get_str(CAPTION_LOCATION)
    caption.stage_path = save.get_str(CAPTION_STAGE_PATH)

    autosave = save.get_int(CAPTION_AUTOSAVE)
    if autosave is not None:
        caption.autosave = bool(autosave)

    stamp = [save.get_int(field) for field in CAPTION_TIME]
    if all(value is not None for value in stamp) and 1900 < stamp[0] < 2200:
        try:
            caption.saved_at = "%04d-%02d-%02d %02d:%02d" % tuple(stamp)
        except TypeError:  # pragma: no cover - guarded by the check above
            caption.saved_at = None

    start = bytes(save.data).find(_JPEG_SOI)
    if start >= 0:
        caption.thumbnail = _jpeg_size(bytes(save.data), start)
    return caption


@dataclass
class SlotInfo:
    index: int
    directory: str
    progress_path: str
    caption_path: Optional[str]
    mtime: float
    size: int

    @property
    def label(self) -> str:
        return f"slot_{self.index:02d}"

    @property
    def caption(self) -> Optional[Caption]:
        return read_caption(self.caption_path) if self.caption_path else None


def find_title_dirs() -> List[str]:
    """Best-effort discovery of save roots created by common launchers."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Library", "Application Support", "nxnative"),
        os.path.join(home, "Library", "Application Support", "NX2Apple"),
        os.path.join(home, ".local", "share", "nxnative"),
    ]
    roots: List[str] = []
    for base in candidates:
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            full = os.path.join(base, entry)
            if os.path.isdir(os.path.join(full, "save")) or os.path.isdir(
                os.path.join(full, "save.work")
            ):
                roots.append(full)
    return roots


class SaveDirectory:
    """A ``<title-id>`` folder containing ``save/`` and optionally ``save.work/``."""

    def __init__(self, root: str) -> None:
        root = os.path.abspath(os.path.expanduser(root))
        base = os.path.basename(root)
        if base in ("save", "save.work"):
            root = os.path.dirname(root)
        self.root = root
        self.save_dir = os.path.join(root, "save")
        self.work_dir = os.path.join(root, "save.work")
        if not os.path.isdir(self.save_dir) and not os.path.isdir(self.work_dir):
            raise FileNotFoundError(f"{root} does not look like a save directory")

    # -------------------------------------------------------------- inventory

    @property
    def has_work_copy(self) -> bool:
        return os.path.isdir(self.work_dir)

    def slots(self, *, source: str = "save") -> List[SlotInfo]:
        """Slot descriptors, ordered by index."""
        base = self.save_dir if source == "save" else self.work_dir
        if not os.path.isdir(base):
            return []
        found: List[SlotInfo] = []
        for entry in sorted(os.listdir(base)):
            if not entry.startswith("slot_"):
                continue
            directory = os.path.join(base, entry)
            progress = os.path.join(directory, PROGRESS)
            if not os.path.isfile(progress):
                continue
            try:
                index = int(entry.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            caption = os.path.join(directory, CAPTION)
            stat = os.stat(progress)
            found.append(
                SlotInfo(
                    index=index,
                    directory=directory,
                    progress_path=progress,
                    caption_path=caption if os.path.isfile(caption) else None,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                )
            )
        return sorted(found, key=lambda s: s.index)

    def active_slot(self, *, source: str = "save") -> Optional[SlotInfo]:
        """The slot the game would load: the most recently written one."""
        slots = self.slots(source=source)
        if not slots:
            return None
        return max(slots, key=lambda s: s.mtime)

    def ordering_conflict(self, *, source: str = "save") -> bool:
        """True when the newest file is not the newest save by its own clock.

        File mtimes are a proxy: copying a save tree, or restoring a backup,
        rewrites them.  ``caption.sav`` carries the clock the Load screen shows.
        When the two disagree the game's own clock is the one to trust, and the
        caller should say so rather than silently pick a slot.
        """
        slots = self.slots(source=source)
        stamped = [(slot, slot.caption) for slot in slots]
        stamped = [(s, c) for s, c in stamped if c and c.saved_at]
        if len(stamped) < 2:
            return False
        newest_file = max(stamped, key=lambda pair: pair[0].mtime)[1].saved_at
        newest_clock = max(stamped, key=lambda pair: pair[1].saved_at)[1].saved_at
        return newest_file != newest_clock

    def open_slot(self, index: int, *, source: str = "save") -> SaveFile:
        base = self.save_dir if source == "save" else self.work_dir
        return SaveFile(os.path.join(base, f"slot_{index:02d}", PROGRESS))

    def open_all(self, *, source: str = "save") -> Dict[int, SaveFile]:
        return {slot.index: self.open_slot(slot.index, source=source) for slot in self.slots(source=source)}

    def open_shared(self, name: str = "option.sav", *, source: str = "save") -> Optional[SaveFile]:
        base = self.save_dir if source == "save" else self.work_dir
        path = os.path.join(base, name)
        return SaveFile(path) if os.path.isfile(path) else None

    # ----------------------------------------------------------------- safety

    def running_hint(self, window: float = 30.0) -> bool:
        """Heuristic: was anything written in the save tree very recently?

        Not a process check -- that is unreliable across platforms and
        sandboxes -- but a write inside the last ``window`` seconds while you
        are not the one writing is a strong signal the game is live.
        """
        newest = 0.0
        for source in ("save", "save.work"):
            for slot in self.slots(source=source):
                newest = max(newest, slot.mtime)
        return bool(newest) and (time.time() - newest) < window

    def backup(self, tag: str = "backup") -> str:
        """Copy ``save/`` next to itself as ``<name>-save-<tag>-<timestamp>``."""
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = f"{self.root}-save-{tag}-{stamp}"
        shutil.copytree(self.save_dir, target)
        return target

    # --------------------------------------------------------------- writing

    def mirror_to_work(self) -> bool:
        """Make ``save.work/`` an exact copy of ``save/``.

        The engine rebuilds ``save.work`` when the game starts, but a stale copy
        left behind by an unclean exit can win.  Mirrored copies remove the
        guesswork.
        """
        if not os.path.isdir(self.work_dir):
            return False
        for entry in os.listdir(self.save_dir):
            src = os.path.join(self.save_dir, entry)
            dst = os.path.join(self.work_dir, entry)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        return True

    def save_all(self, saves: Dict[int, SaveFile], *, mirror: bool = True) -> List[str]:
        """Write every slot back, then mirror into ``save.work``."""
        written = [save.save(os.path.join(self.save_dir, f"slot_{index:02d}", PROGRESS))
                   for index, save in sorted(saves.items())]
        if mirror:
            self.mirror_to_work()
        return written
