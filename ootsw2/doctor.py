"""Why an edit did or did not take effect.

Four different failures look identical from the outside: the game boots and the
number you changed is the old number.  They are told apart by looking at the
directory rather than at the field:

1. the game was still running, and flushed its memory over your write;
2. you edited a slot the game will not load, because it loads the newest;
3. you edited ``save/`` while the engine mounts ``save.work/``;
4. the value is in a field that only draws a number and does not grant anything.

(4) cannot be checked here -- it depends on the field.  (1)-(3) can, and they
account for every silent failure this project ran into.

``examine`` returns findings instead of printing, so the same checks can run
from a script or a front end.  Every check states what it measured, because a
report that says "ok" without saying what it compared is not worth reading.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .container import SaveFile, SaveFormatError
from .savedir import Caption, SaveDirectory, read_caption

__all__ = ["Finding", "examine", "exit_code"]

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Finding:
    level: str
    code: str
    message: str
    detail: str = ""

    @property
    def is_problem(self) -> bool:
        return self.level != OK


def _digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree(base: str) -> Dict[str, str]:
    """Relative path -> content digest for every file under ``base``."""
    found: Dict[str, str] = {}
    if not os.path.isdir(base):
        return found
    for parent, _dirs, files in os.walk(base):
        for name in files:
            full = os.path.join(parent, name)
            found[os.path.relpath(full, base)] = _digest(full)
    return found


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _age(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def _game_log(directory: SaveDirectory) -> Optional[str]:
    """The engine's own log for this title, if it is where nxnative puts it."""
    title = os.path.basename(directory.root)
    home = os.path.expanduser("~")
    for candidate in (
        os.path.join(home, "Library", "Logs", "nxnative", f"{title}.log"),
        os.path.join(home, "Library", "Logs", "nxnative", f"{title}.log.txt"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _backups(directory: SaveDirectory) -> List[str]:
    """Backup folders next to the save, as ``SaveDirectory.backup`` names them."""
    parent = os.path.dirname(directory.root)
    stem = os.path.basename(directory.root)
    found = []
    if os.path.isdir(parent):
        for entry in sorted(os.listdir(parent)):
            if entry.startswith(f"{stem}-save-"):
                full = os.path.join(parent, entry)
                if os.path.isdir(full):
                    found.append(full)
    return found


def examine(directory: SaveDirectory) -> List[Finding]:
    findings: List[Finding] = []

    slots = directory.slots()
    work_slots = directory.slots(source="save.work")

    if not slots:
        findings.append(Finding(
            FAIL, "no-slots",
            f"no slot_* folders with a {os.path.basename(directory.save_dir)}/progress.sav",
            "nothing here can be loaded, so nothing here can be edited",
        ))
        return findings

    captions: Dict[int, Optional[Caption]] = {
        slot.index: (read_caption(slot.caption_path) if slot.caption_path else None)
        for slot in slots
    }

    # -- 1. is the game running? -------------------------------------------
    # The save tree is a weak signal: a tool that just wrote it looks exactly
    # like a game that is running.  The engine's log is a strong one, because
    # it is written continuously and nothing else touches it.
    newest = max((slot.mtime for slot in slots + work_slots), default=0.0)
    age = _age(time.time() - newest) if newest else "never"
    log = _game_log(directory)
    log_age = time.time() - os.path.getmtime(log) if log else None

    if log_age is not None and log_age < 10:
        findings.append(Finding(
            WARN, "running",
            f"the game is running (its log was written {_age(log_age)} ago)",
            f"{os.path.basename(log)} -- quit to the home screen and close it "
            "before editing: it holds its state in memory and flushes it over "
            "the directory when it exits",
        ))
    elif not newest:
        findings.append(Finding(WARN, "no-mtime", "no file times to read"))
    elif directory.running_hint():
        findings.append(Finding(
            WARN, "recent-write",
            f"something wrote to this tree {age} ago",
            "no engine log found to tell a running game from a tool that just "
            "finished; if that was you, ignore this. If the game is open, quit "
            "it first.",
        ))
    else:
        how = "the game is not writing"
        if log:
            how += f" (its log last changed {_age(log_age)} ago)"
        findings.append(Finding(OK, "idle", f"{how}, newest save change {age} ago"))

    # -- 2. does save/ match what the engine will mount? --------------------
    if not directory.has_work_copy:
        findings.append(Finding(
            OK, "no-work",
            "no save.work/ right now",
            "the engine creates it at launch; edits to save/ are what it reads next",
        ))
    else:
        left = _tree(directory.save_dir)
        right = _tree(directory.work_dir)
        shared = set(left) & set(right)
        differing = sorted(name for name in shared if left[name] != right[name])
        only_left = sorted(set(left) - set(right))
        only_right = sorted(set(right) - set(left))
        if not differing and not only_left and not only_right:
            findings.append(Finding(
                OK, "work-identical",
                f"save/ and save.work/ agree ({_plural(len(left), 'file')})",
            ))
        else:
            detail = []
            if differing:
                detail.append(f"{_plural(len(differing), 'file')} differ: " + ", ".join(differing[:4]))
            if only_left:
                detail.append(f"{len(only_left)} only in save/: " + ", ".join(only_left[:4]))
            if only_right:
                detail.append(f"{len(only_right)} only in save.work/: " + ", ".join(only_right[:4]))
            findings.append(Finding(
                WARN, "work-differs",
                "save/ and save.work/ do not match",
                "; ".join(detail) + " -- while the game runs it mounts save.work/, "
                "so an edit to save/ alone can be overwritten on exit. "
                "`ootsw2 set` writes both and then mirrors; a hand edit does not.",
            ))

    # -- 3. do the slots parse? --------------------------------------------
    broken = []
    counts = []
    for slot in slots:
        try:
            counts.append(len(SaveFile(slot.progress_path)))
        except (OSError, SaveFormatError) as error:
            broken.append(f"{slot.label}: {error}")
    if broken:
        findings.append(Finding(
            FAIL, "unreadable",
            f"{len(broken)} of {_plural(len(slots), 'slot')} do not parse",
            "; ".join(broken[:3]),
        ))
    else:
        low, high = min(counts), max(counts)
        spread = f"{low} field(s) each" if low == high else f"{low}-{high} field(s)"
        findings.append(Finding(OK, "parse",
                                f"{_plural(len(slots), 'slot')} parse, {spread}"))

    # -- 4. which one will the game load? ----------------------------------
    active = directory.active_slot()
    if active:
        caption = captions.get(active.index)
        where = caption.location if caption and caption.location else "unknown place"
        when = caption.saved_at if caption and caption.saved_at else "unknown time"
        kind = caption.kind if caption else "-"
        findings.append(Finding(
            OK, "active",
            f"the game loads {active.label} ({when}, {kind}, {where})",
            "by file time; the game's own clock is checked next",
        ))

    # -- 5. does the game's clock agree with the file times? ---------------
    stamped = [slot for slot in slots
               if captions.get(slot.index) and captions[slot.index].saved_at]
    if len(stamped) >= 2:
        by_file = max(stamped, key=lambda slot: slot.mtime)
        newest_clock = max(captions[slot.index].saved_at for slot in stamped)
        # Compare the newest file against the newest clock rather than against
        # whichever slot happens to sort first: the clock has minute resolution,
        # so two saves a few seconds apart share a stamp and are not a conflict.
        if captions[by_file.index].saved_at == newest_clock:
            tied = sum(1 for slot in stamped if captions[slot.index].saved_at == newest_clock)
            findings.append(Finding(
                OK, "clock-agrees",
                f"file times and the game's clock both point at {by_file.label}"
                + (f" ({tied} slots share {newest_clock})" if tied > 1 else ""),
            ))
        else:
            by_clock = max(stamped, key=lambda slot: captions[slot.index].saved_at)
            clock = captions[by_clock.index]
            where = f" in {clock.location}" if clock.location else ""
            findings.append(Finding(
                WARN, "clock-conflict",
                f"file times point at {by_file.label}, the game's clock at {by_clock.label}",
                f"{by_clock.label} was saved at {clock.saved_at}{where}, later than "
                f"{by_file.label}. Copying or restoring a tree rewrites file times, and "
                "the clock is what the Load screen shows. Editing the wrong slot is a "
                "silent no-op.",
            ))

    # -- 6. can this be undone? --------------------------------------------
    backups = _backups(directory)
    if backups:
        newest_backup = max(backups, key=os.path.getmtime)
        findings.append(Finding(
            OK, "backup",
            f"{_plural(len(backups), 'backup')} next to the save",
            f"newest: {os.path.basename(newest_backup)}",
        ))
    else:
        findings.append(Finding(
            WARN, "no-backup",
            "no backup next to the save",
            "`ootsw2 set` copies one before writing; a hand edit has nothing to go back to",
        ))

    return findings


def exit_code(findings: List[Finding]) -> int:
    if any(finding.level == FAIL for finding in findings):
        return 2
    if any(finding.level == WARN for finding in findings):
        return 1
    return 0
