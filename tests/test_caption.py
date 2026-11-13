"""caption.sav: the record the Load screen draws, and the string-length guard."""

import json
import struct

from ootsw2.cli import main
from ootsw2.container import MAGIC, VERSION, SaveFile, is_inline_scalar
from ootsw2.savedir import (
    CAPTION_AUTOSAVE,
    CAPTION_LOCATION,
    CAPTION_STAGE_PATH,
    CAPTION_TIME,
    SaveDirectory,
    read_caption,
)


def build_raw(pairs, *, spare=0, trailer=b"", version=VERSION):
    """A container from raw ``(key id, value)`` pairs, strings allowed as values."""
    table_length = (len(pairs) + spare) * 8
    base = 40 + table_length
    payload = bytearray()
    table = bytearray()
    for key, value in pairs:
        if isinstance(value, str):
            offset = base + len(payload)
            payload.extend(value.encode("ascii") + b"\x00")
            table.extend(struct.pack("<II", key, offset))
        else:
            table.extend(struct.pack("<II", key, value & 0xFFFFFFFF))
    table.extend(b"\x00" * (spare * 8))
    header_end = 40 + len(table)
    assert header_end == base
    header = struct.pack("<III", MAGIC, version, header_end) + b"\x00" * 28
    return header + bytes(table) + bytes(payload) + trailer


def fake_jpeg(width=543, height=306):
    """A JPEG header the size reader can walk: SOI, APP0, then SOF0."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", height, width) + b"\x03"
            + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def caption_bytes(*, when=(2026, 11, 13, 13, 23), autosave=1, location="KakarikoVillage",
                  stage="KakarikoVillage/KakarikoVillage_Child", jpeg=True):
    pairs = [
        (CAPTION_LOCATION, location),
        (CAPTION_STAGE_PATH, stage),
        (CAPTION_AUTOSAVE, autosave),
    ]
    pairs += list(zip(CAPTION_TIME, when))
    return build_raw(pairs, spare=8, trailer=fake_jpeg() if jpeg else b"")


def write_caption(path, **kwargs):
    path.write_bytes(caption_bytes(**kwargs))
    return path


def test_caption_reports_clock_location_and_kind(tmp_path):
    caption = read_caption(str(write_caption(tmp_path / "caption.sav")))
    assert caption is not None
    assert caption.saved_at == "2026-11-13 13:23"
    assert caption.location == "KakarikoVillage"
    assert caption.stage_path == "KakarikoVillage/KakarikoVillage_Child"
    assert caption.autosave is True
    assert caption.kind == "auto"


def test_caption_manual_save(tmp_path):
    path = write_caption(tmp_path / "caption.sav", autosave=0)
    assert read_caption(str(path)).kind == "manual"


def test_caption_thumbnail_size_is_read_from_the_jpeg_header(tmp_path):
    path = write_caption(tmp_path / "caption.sav")
    assert read_caption(str(path)).thumbnail == (543, 306)


def test_caption_without_a_thumbnail(tmp_path):
    path = write_caption(tmp_path / "caption.sav", jpeg=False)
    assert read_caption(str(path)).thumbnail is None


def test_missing_caption_is_not_an_error(tmp_path):
    assert read_caption(str(tmp_path / "nope.sav")) is None


def test_a_broken_caption_is_not_an_error(tmp_path):
    path = tmp_path / "caption.sav"
    path.write_bytes(b"not a save")
    assert read_caption(str(path)) is None


def test_slot_exposes_its_caption(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    slot = directory.slots()[0]
    assert slot.caption is None  # the fixture writes no caption.sav
    write_caption(slot_dir / "save" / "slot_00" / "caption.sav")
    assert SaveDirectory(str(slot_dir)).slots()[0].caption.location == "KakarikoVillage"


def test_slots_command_shows_the_game_clock(slot_dir, capsys):
    for index in range(6):
        write_caption(slot_dir / "save" / f"slot_{index:02d}" / "caption.sav",
                      when=(2026, 11, 13, 13, 10 + index), autosave=index % 2,
                      location=f"Room{index}")
    code = main(["slots", str(slot_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "2026-11-13 13:15" in out
    assert "Room5" in out
    assert "manual" in out and "auto" in out
    assert "543x306" in out


def test_slots_command_json_carries_the_caption(slot_dir, capsys):
    write_caption(slot_dir / "save" / "slot_05" / "caption.sav", autosave=0, location="Market")
    code = main(["slots", str(slot_dir), "--json"])
    out = capsys.readouterr().out
    assert code == 0
    rows = json.loads(out)
    newest = [row for row in rows if row["slot"] == "slot_05"][0]
    assert newest["kind"] == "manual"
    assert newest["location"] == "Market"
    assert newest["saved"] == "2026-11-13 13:23"
    assert newest["active"] is True


def test_ordering_conflict_flags_a_copied_tree(slot_dir):
    for index in range(6):
        write_caption(slot_dir / "save" / f"slot_{index:02d}" / "caption.sav",
                      when=(2026, 11, 13, 12, 0), autosave=1)
    write_caption(slot_dir / "save" / "slot_02" / "caption.sav",
                  when=(2026, 11, 13, 18, 0), autosave=1)
    # mtime still says slot_05; the captions say slot_02.
    assert SaveDirectory(str(slot_dir)).ordering_conflict() is True


def test_no_conflict_when_the_orderings_agree(slot_dir):
    for index in range(6):
        write_caption(slot_dir / "save" / f"slot_{index:02d}" / "caption.sav",
                      when=(2026, 11, 13, 12, index), autosave=1)
    assert SaveDirectory(str(slot_dir)).ordering_conflict() is False


def test_a_one_character_payload_word_is_not_a_string():
    """A large integer can land inside the payload; 0x56 is not the word "V"."""
    # One entry, so the payload starts at 48 and that is also its first offset.
    data = build_raw([(0x11111111, 48)], trailer=b"V\x00" + b"\x00" * 6)
    save = SaveFile("progress.sav", data)
    value = save.get_raw(0x11111111)
    assert value == save.header_end
    assert is_inline_scalar(save.data, save.header_end, value) is True
    assert save.get_str(0x11111111) is None


def test_a_real_identifier_still_reads():
    data = build_raw([(0x22222222, "Weapon_Sword_Master")])
    save = SaveFile("progress.sav", data)
    assert save.get_str(0x22222222) == "Weapon_Sword_Master"


def test_map_marker_fields_are_named():
    from ootsw2.fields import DICTIONARY
    assert DICTIONARY.id_of("Player_Pos_For_Map") == 0x960AD56A
    assert DICTIONARY.id_of("Player_Rot_For_Map") == 0xA4AEE8CD
