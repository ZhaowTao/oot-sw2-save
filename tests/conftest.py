"""Shared helpers: build synthetic save containers without any game data."""

import struct

import pytest

from ootsw2.container import HEADER_SIZE, MAGIC, VERSION
from ootsw2.hash import field_id

FREE = object()


def build_save(entries, *, spare_slots=0, magic=MAGIC, version=VERSION, payload_extra=b""):
    """Assemble a container.

    ``entries`` is a list of ``(name, value)`` pairs.  ``value`` is an int, a
    ``str`` (stored in the payload pool), or :data:`FREE` for an empty table
    slot.  Names are hashed with the real derivation.
    """
    payload = bytearray(payload_extra)
    table = bytearray()

    def put_string(text):
        offset = HEADER_SIZE + (len(entries) + spare_slots) * 8 + len(payload)
        payload.extend(text.encode("ascii"))
        payload.append(0)
        return offset

    for name, value in entries:
        key = field_id(name)
        if value is FREE:
            table.extend(struct.pack("<II", 0, 0))
            continue
        stored = put_string(value) if isinstance(value, str) else value
        table.extend(struct.pack("<II", key, stored & 0xFFFFFFFF))

    for _ in range(spare_slots):
        table.extend(struct.pack("<II", 0, 0))

    header_end = HEADER_SIZE + len(table)
    header = struct.pack("<III", magic, version, header_end) + b"\x00" * (HEADER_SIZE - 12)
    return header + bytes(table) + bytes(payload)


@pytest.fixture
def sample_bytes(tmp_path):
    data = build_save(
        [
            ("PlayerStatus.CurrentRupee", 666),
            ("PlayerStatus.Life", 48),
            ("PlayerStatus.DiveDepth", 0x41100000),
            ("PlayerStatus.EquipWeapon", "Weapon_Sword_Master"),
        ],
        spare_slots=2,
    )
    path = tmp_path / "progress.sav"
    path.write_bytes(data)
    return path


@pytest.fixture
def slot_dir(tmp_path):
    """A minimal save directory with six slots and a save.work mirror."""
    import os
    import time

    root = tmp_path / "0400486024DEC000"
    save = root / "save"
    save.mkdir(parents=True)
    (root / "save.work").mkdir()

    for index in range(6):
        directory = save / f"slot_{index:02d}"
        directory.mkdir()
        data = build_save(
            [
                ("PlayerStatus.CurrentRupee", 100 + index),
                ("PlayerStatus.DiveDepth", 0x40C00000),
            ],
            spare_slots=1,
        )
        target = directory / "progress.sav"
        target.write_bytes(data)
        stamp = time.time() - (5 - index) * 60
        os.utime(target, (stamp, stamp))
    (save / "option.sav").write_bytes(
        build_save([("Option.Language", "Lang_English")], spare_slots=1)
    )
    return root
