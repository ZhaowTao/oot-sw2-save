"""Command line interface.

Deliberately small and scriptable: every command works on a single ``*.sav``
*or* on a save directory (in which case it can reach all six rotating slots).
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .container import SaveFile, SaveFormatError, is_inline_scalar
from .doctor import OK, examine, exit_code
from .fields import DICTIONARY, resolve_field
from .hash import field_id
from .savedir import SaveDirectory, find_title_dirs, read_thumbnail


# --------------------------------------------------------------------- helpers


def _fmt_value(save: SaveFile, fid: int) -> Tuple[str, str]:
    """Render a field value plus its kind ('str' | 'float' | 'int')."""
    raw = save.get_raw(fid)
    if raw is None:
        return "-", "int"
    if not is_inline_scalar(save.data, save.header_end, raw):
        text = save.get_str(fid)
        if text is not None:
            return text, "str"
    # Counters and flags are small; a large word that also decodes as a sane
    # float is almost always a float.  This is how DiveDepth (0x41100000)
    # shows up as 9 instead of 1091567616.
    if raw > 0x00FFFFFF:
        as_float = struct.unpack("<f", struct.pack("<I", raw))[0]
        if _float_is_meaningful(as_float):
            return f"{as_float:g}", "float"
    if raw > 0x7FFFFFFF:
        as_signed = struct.unpack("<i", struct.pack("<I", raw))[0]
        return f"{as_signed} (0x{raw:08X})", "int"
    return str(raw), "int"


def _float_is_meaningful(value: float) -> bool:
    """Reject bit patterns that only look like a float by accident."""
    if value != value or value in (float("inf"), float("-inf")):
        return False
    return 1e-4 <= abs(value) < 1e7


def _describe(entry: int) -> str:
    name = DICTIONARY.name_of(entry)
    return name if name else f"<unnamed 0x{entry:08X}>"


def _resolve_targets(path: str, slot: Optional[int], all_slots: bool):
    """Yield ``(label, SaveFile)`` for whatever the user pointed at."""
    expanded = os.path.expanduser(path)
    if os.path.isfile(expanded):
        yield os.path.basename(expanded), SaveFile(expanded)
        return

    directory = SaveDirectory(expanded)
    if all_slots:
        for index, save in directory.open_all().items():
            yield f"slot_{index:02d}", save
        return
    if slot is not None:
        yield f"slot_{slot:02d}", directory.open_slot(slot)
        return
    active = directory.active_slot()
    if active is None:
        raise SystemExit(f"{expanded}: no slots found")
    yield f"{active.label} (newest)", SaveFile(active.progress_path)


def _parse_value(save: SaveFile, fid: int, text: str, kind: str) -> Tuple[str, object]:
    """Decide how to encode ``text`` for this field. Returns (kind, value)."""
    if kind == "auto":
        if save.get_str(fid) is not None:
            kind = "str"
        elif any(ch in text for ch in ".eE") and _parses_as_float(text):
            kind = "float"
        else:
            kind = "int"

    if kind == "str":
        return "str", text

    if kind == "float":
        try:
            return "float", float(text)
        except ValueError:
            raise SystemExit(f"{text!r} is not a number")

    try:
        if text.lower().startswith("0x"):
            return "int", int(text, 16)
        return "int", int(text, 10)
    except ValueError:
        raise SystemExit(f"{text!r} is not an integer (use --type float or --type str)")


def _parses_as_float(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _apply(save: SaveFile, fid: int, kind: str, value: object) -> Optional[int]:
    if kind == "str":
        return save.set_str(fid, str(value))
    if kind == "float":
        return save.set_float(fid, float(value))
    return save.set_int(fid, int(value))


# -------------------------------------------------------------------- commands


def cmd_list(args: argparse.Namespace) -> int:
    rows: List[Dict[str, object]] = []
    for label, save in _resolve_targets(args.path, args.slot, False):
        entries = list(save)
        if args.prefix:
            wanted = args.prefix.lower()
            entries = [fid for fid in entries
                       if (DICTIONARY.name_of(fid) or "").lower().startswith(wanted)]
        if args.search:
            needle = args.search.lower()
            entries = [fid for fid in entries
                       if needle in (DICTIONARY.name_of(fid) or "").lower()]
        if args.named:
            entries = [fid for fid in entries if DICTIONARY.name_of(fid)]
        if args.limit:
            entries = entries[: args.limit]

        for fid in entries:
            text, kind = _fmt_value(save, fid)
            rows.append({
                "slot": label,
                "name": DICTIONARY.name_of(fid),
                "id": fid,
                "value": text,
                "kind": kind,
            })

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print("no matching fields")
        return 0

    width = min(max((len(str(r["name"] or "")) for r in rows), default=10), 58)
    print(f"{'FIELD':<{width}}  {'ID':>10}  VALUE")
    print("-" * (width + 2 + 10 + 2 + 5))
    for row in rows:
        name = row["name"] or f"<unnamed 0x{int(row['id']):08X}>"
        if len(name) > width:
            name = name[: width - 1] + "…"
        print(f"{name:<{width}}  {int(row['id']):>10}  {row['value']}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    out: Dict[str, object] = {}
    for label, save in _resolve_targets(args.path, args.slot, False):
        items: Dict[str, object] = {}
        for reference in args.fields:
            fid, name = resolve_field(reference)
            text, kind = _fmt_value(save, fid)
            key = name or reference
            items[key] = {"id": fid, "value": None if fid not in save else text, "kind": kind}
        out[label] = items

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    for label, items in out.items():
        print(f"[{label}]")
        for key, info in items.items():
            if info["value"] is None:
                print(f"  {key:<44} (absent)")
            else:
                print(f"  {key:<44} {info['value']}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    fid, name = resolve_field(args.field)
    targets = list(_resolve_targets(args.path, args.slot, args.all_slots))
    if not targets:
        raise SystemExit("nothing to edit")

    planned: List[Tuple[str, SaveFile, str, object, str]] = []
    for label, save in targets:
        if fid not in save:
            print(f"  ! {label}: field absent, skipping", file=sys.stderr)
            continue
        kind, value = _parse_value(save, fid, args.value, args.type)
        previous_text, _previous_kind = _fmt_value(save, fid)
        planned.append((label, save, kind, value, previous_text))

    if not planned:
        return 1

    if args.dry_run:
        for label, _save, kind, value, before in planned:
            print(f"[dry-run] {label}: {name or fid} {before!r} -> {value!r} ({kind})")
        return 0

    if args.backup and os.path.isdir(os.path.expanduser(args.path)):
        target = SaveDirectory(args.path).backup(tag="before-edit")
        print(f"backup -> {target}")

    for label, save, kind, value, previous_text in planned:
        _apply(save, fid, kind, value)
        save.save()
        print(f"  {label:<22} {name or fid}: {previous_text} -> {value} ({kind})")

    if args.all_slots and os.path.isdir(os.path.expanduser(args.path)):
        directory = SaveDirectory(args.path)
        if directory.mirror_to_work():
            print("  mirrored save/ -> save.work/")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    before = SaveFile(os.path.expanduser(args.before))
    after = SaveFile(os.path.expanduser(args.after))
    changes = before.diff(after, DICTIONARY.id_map())
    if args.named_only:
        changes = [c for c in changes if c.name]
    if args.limit:
        changes = changes[: args.limit]

    rows = []
    for change in changes:
        text_before, _ = _fmt_value(before, change.field_id) if change.before is not None else ("-", "")
        text_after, _ = _fmt_value(after, change.field_id) if change.after is not None else ("-", "")
        rows.append({
            "kind": change.kind,
            "name": change.name,
            "id": change.field_id,
            "before": text_before,
            "after": text_after,
        })

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print("no differences")
        return 0

    width = min(max((len(str(r["name"] or "")) for r in rows), default=10), 52)
    print(f"{len(rows)} field(s) differ")
    print(f"{'KIND':<8}{'FIELD':<{width}}  {'BEFORE':>14}  {'AFTER':>14}")
    print("-" * (8 + width + 34))
    for row in rows:
        name = row["name"] or f"<unnamed 0x{int(row['id']):08X}>"
        if len(name) > width:
            name = name[: width - 1] + "…"
        print(f"{row['kind']:<8}{name:<{width}}  {str(row['before']):>14}  {str(row['after']):>14}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Ask whether a set of candidate names exist in a save."""
    targets = list(_resolve_targets(args.path, args.slot, False))
    if not targets:
        raise SystemExit("nothing to probe")
    label, save = targets[0]

    print(f"probing {label} ({len(save)} fields)")
    hits = 0
    for reference in args.names:
        fid, _name = resolve_field(reference)
        present = fid in save
        hits += present
        if present:
            text, kind = _fmt_value(save, fid)
            print(f"  hit    {reference:<52} {text}  ({kind})")
        else:
            print(f"  miss   {reference}")
    print(f"\n{hits}/{len(args.names)} present")
    return 0 if hits else 2


def cmd_names(args: argparse.Namespace) -> int:
    names = DICTIONARY.search(args.search) if args.search else DICTIONARY.names()
    if args.prefix:
        names = [n for n in names if n.startswith(args.prefix)]
    if args.limit:
        names = names[: args.limit]
    for name in names:
        print(name)
    print(f"\n{len(names)} name(s); dictionary holds {len(DICTIONARY)}", file=sys.stderr)
    return 0


def cmd_slots(args: argparse.Namespace) -> int:
    directory = SaveDirectory(args.path)
    slots = directory.slots()
    if not slots:
        raise SystemExit(f"{directory.save_dir}: no slots")
    active = directory.active_slot()
    work = directory.slots(source="save.work")
    work_by_index = {slot.index: slot for slot in work}

    if not args.json:
        print(f"root     {directory.root}")
        print(f"work copy {'present' if directory.has_work_copy else 'absent'} "
              f"({len(work)} slot(s))")
        print()

    rows = []
    for slot in slots:
        caption = slot.caption
        try:
            fields = str(len(SaveFile(slot.progress_path)))
        except SaveFormatError:
            fields = "?"
        peer = work_by_index.get(slot.index)
        same = "same" if peer and peer.size == slot.size else ("differs" if peer else "-")
        rows.append({
            "slot": slot.label,
            "index": slot.index,
            "saved": (caption.saved_at if caption and caption.saved_at else "-"),
            "kind": caption.kind if caption else "-",
            "location": (caption.location if caption and caption.location else "-"),
            "size": slot.size,
            "fields": fields,
            "work": same,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(slot.mtime)),
            "active": bool(active and slot.index == active.index),
        })

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        if directory.running_hint():
            print("! something wrote to this save tree in the last 30 s", file=sys.stderr)
        return 0

    location_width = min(max((len(r["location"]) for r in rows), default=8), 22)
    print(f"{'SLOT':<8}{'SAVED (game clock)':<20}{'KIND':<8}"
          f"{'LOCATION':<{location_width}}{'SIZE':>9}{'FIELDS':>8}{'WORK':>7}  STATUS")
    for row in rows:
        location = row["location"]
        if len(location) > location_width:
            location = location[: location_width - 1] + "…"
        status = "ACTIVE (game loads this)" if row["active"] else ""
        print(f"{row['slot']:<8}{row['saved']:<20}{row['kind']:<8}"
              f"{location:<{location_width}}{row['size']:>9}{row['fields']:>8}"
              f"{row['work']:>7}  {status}")

    if directory.ordering_conflict():
        newest_by_clock = max(
            (row for row in rows if row["saved"] != "-"),
            key=lambda row: row["saved"],
            default=None,
        )
        if newest_by_clock:
            print(f"\n! file times and the game's own clock disagree: {newest_by_clock['slot']} "
                  f"is the newest save ({newest_by_clock['saved']}), but another slot has a "
                  f"newer file time. Copying or restoring the tree rewrites mtimes.")

    thumbnail = next((slot.caption.thumbnail for slot in slots
                      if slot.caption and slot.caption.thumbnail), None)
    if thumbnail:
        print(f"\nthumbnails: {thumbnail[0]}x{thumbnail[1]} JPEG in each caption.sav "
              f"(ootsw2 thumb exports them)")

    if directory.running_hint():
        print("\n! something wrote to this save tree in the last 30 s -- "
              "quit the game before editing")
    return 0


def cmd_thumb(args: argparse.Namespace) -> int:
    directory = SaveDirectory(args.path)
    slots = directory.slots()
    if not slots:
        raise SystemExit(f"{directory.save_dir}: no slots")
    if args.index is not None:
        slots = [slot for slot in slots if slot.index == args.index]
        if not slots:
            raise SystemExit(f"{directory.save_dir}: no slot_{args.index:02d}")

    written = []
    for slot in slots:
        caption = slot.caption
        blob = read_thumbnail(slot.caption_path) if slot.caption_path else None
        row = {
            "slot": slot.label,
            "saved": caption.saved_at if caption else None,
            "kind": caption.kind if caption else None,
            "location": caption.location if caption else None,
            "width": caption.thumbnail[0] if caption and caption.thumbnail else None,
            "height": caption.thumbnail[1] if caption and caption.thumbnail else None,
            "bytes": len(blob) if blob else None,
            "path": None,
        }
        if blob is not None:
            if not args.dry_run:
                os.makedirs(args.out, exist_ok=True)
                target = os.path.join(args.out, f"{slot.label}.jpg")
                with open(target, "wb") as handle:
                    handle.write(blob)
                row["path"] = target
            written.append(row)
        else:
            row["error"] = "no JPEG in caption.sav"
            written.append(row)

    if args.json:
        print(json.dumps(written, indent=2, ensure_ascii=False))
        return 0

    print(f"{'SLOT':<8}{'SAVED (game clock)':<20}{'KIND':<8}{'LOCATION':<20}"
          f"{'PIXELS':>10}{'KB':>7}  FILE")
    for row in written:
        pixels = f"{row['width']}x{row['height']}" if row["width"] else "-"
        size = f"{row['bytes'] / 1024:.0f}" if row["bytes"] else "-"
        note = row["path"] or row.get("error") or "(dry run)"
        print(f"{row['slot']:<8}{(row['saved'] or '-'):<20}{(row['kind'] or '-'):<8}"
              f"{(row['location'] or '-')[:20]:<20}{pixels:>10}{size:>7}  {note}")

    if not args.dry_run and written:
        print(f"\n{len(written)} thumbnail(s) -> {args.out}")
        print("These are the images the game's own Load screen draws, byte for byte.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    directory = SaveDirectory(args.path)
    findings = examine(directory)

    if args.json:
        print(json.dumps([finding.__dict__ for finding in findings], indent=2,
                         ensure_ascii=False))
        return exit_code(findings)

    print(f"root     {directory.root}")
    print()
    for finding in findings:
        print(f"  {finding.level:<5} {finding.message}")
        if finding.detail:
            for line in _wrap(finding.detail, 72):
                print(f"        {line}")

    ok = sum(1 for finding in findings if finding.level == OK)
    problems = len(findings) - ok
    print()
    if problems:
        print(f"{ok} ok, {problems} to look at")
    else:
        print(f"{ok} checks, all clear")
    return exit_code(findings)


def _wrap(text: str, width: int) -> List[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def cmd_verify_dict(args: argparse.Namespace) -> int:
    bad = DICTIONARY.unverified()
    print(f"dictionary entries: {len(DICTIONARY)}")
    print(f"hash-consistent   : {len(DICTIONARY) - len(bad)}")
    print(f"legacy aliases    : {len(bad)}")
    for name, stored, computed in bad:
        print(f"  {name:<48} stored={stored:<12} murmur3={computed}")
    return 0 if not bad else 0


def cmd_roots(args: argparse.Namespace) -> int:
    roots = find_title_dirs()
    if not roots:
        print("no save directories found", file=sys.stderr)
        return 1
    for root in roots:
        print(root)
    return 0


# ----------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ootsw2",
        description="Read and edit Ocarina of Time (Switch 2) save files.",
        epilog="Field names are resolved with murmur3_32(name); see "
               "`ootsw2 names` for the built-in dictionary.",
    )
    parser.add_argument("--version", action="version", version="ootsw2 0.4.0")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_target(p: argparse.ArgumentParser) -> None:
        p.add_argument("path", help="a *.sav file, or a save directory")
        p.add_argument("--slot", type=int, help="slot index 0-5 (default: newest)")

    p_list = sub.add_parser("list", help="list fields and values")
    add_target(p_list)
    p_list.add_argument("--prefix", help="only names starting with this")
    p_list.add_argument("--search", help="only names containing this")
    p_list.add_argument("--named", action="store_true", help="skip unnamed fields")
    p_list.add_argument("--limit", type=int, default=0)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="print specific fields")
    add_target(p_get)
    p_get.add_argument("fields", nargs="+", help="names or numeric ids")
    p_get.add_argument("--json", action="store_true")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="write a field")
    add_target(p_set)
    p_set.add_argument("field", help="name or numeric id")
    p_set.add_argument("value", help="new value")
    p_set.add_argument("--type", choices=["auto", "int", "float", "str"], default="auto")
    p_set.add_argument("--all-slots", action="store_true",
                       help="write every slot and mirror into save.work/")
    p_set.add_argument("--backup", action="store_true", default=True)
    p_set.add_argument("--no-backup", dest="backup", action="store_false")
    p_set.add_argument("--dry-run", action="store_true")
    p_set.set_defaults(func=cmd_set)

    p_diff = sub.add_parser("diff", help="compare two save files field by field")
    p_diff.add_argument("before")
    p_diff.add_argument("after")
    p_diff.add_argument("--json", action="store_true")
    p_diff.add_argument("--named-only", action="store_true",
                        help="hide fields the dictionary has no name for")
    p_diff.add_argument("--limit", type=int, default=0)
    p_diff.set_defaults(func=cmd_diff)

    p_probe = sub.add_parser("probe", help="test whether candidate field names exist")
    add_target(p_probe)
    p_probe.add_argument("names", nargs="+")
    p_probe.set_defaults(func=cmd_probe)

    p_names = sub.add_parser("names", help="search the built-in dictionary")
    p_names.add_argument("--search")
    p_names.add_argument("--prefix")
    p_names.add_argument("--limit", type=int, default=0)
    p_names.set_defaults(func=cmd_names)

    p_slots = sub.add_parser("slots", help="show the rotating slots of a save directory")
    p_slots.add_argument("path")
    p_slots.add_argument("--json", action="store_true")
    p_slots.set_defaults(func=cmd_slots)

    p_thumb = sub.add_parser("thumb", help="export each slot's Load-screen thumbnail")
    p_thumb.add_argument("path")
    p_thumb.add_argument("-o", "--out", default="thumbs",
                         help="directory to write the JPEGs into (default: thumbs)")
    p_thumb.add_argument("-i", "--index", type=int,
                         help="only this slot index")
    p_thumb.add_argument("--dry-run", action="store_true",
                         help="show what would be written, write nothing")
    p_thumb.add_argument("--json", action="store_true")
    p_thumb.set_defaults(func=cmd_thumb)

    p_doctor = sub.add_parser("doctor",
                              help="check why an edit would or would not take effect")
    p_doctor.add_argument("path")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.set_defaults(func=cmd_doctor)

    p_verify = sub.add_parser("verify-dict", help="check the dictionary against the hash")
    p_verify.set_defaults(func=cmd_verify_dict)

    p_roots = sub.add_parser("roots", help="find save directories on this machine")
    p_roots.set_defaults(func=cmd_roots)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (SaveFormatError, FileNotFoundError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
