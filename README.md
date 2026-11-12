# oot-sw2-save

Read and edit save files from **The Legend of Zelda: Ocarina of Time** on
Nintendo Switch 2 (the 2026 remake — not the N64 original, not OoT3D, not Ship
of Harkinian).

[![tests](https://github.com/ZhaowTao/oot-sw2-save/actions/workflows/tests.yml/badge.svg)](https://github.com/ZhaowTao/oot-sw2-save/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

---

## Why this exists

If you have edited a save file for this game and seen absolutely nothing change
in game, you were almost certainly the victim of this:

> The game keeps **six rotating `progress.sav` slots** and loads only the newest
> one. It also mounts a **transactional working copy** (`save.work`) while it
> runs, and flushes its in-memory state over the directory when it exits.

Edit `slot_05` and the game loads `slot_02`: your edit did nothing. Edit `save/`
while the game is running: your edit is overwritten wholesale. Both failures
look identical from the outside — the game boots, and the number you changed is
the old number.

On top of that, the field key is not a sequential index. It is a hash:

```python
field_id("PlayerStatus.DiveDepth")              # 1632005153
field_id("PouchData.Item_Scale_Gold.StockNum")  # 1256920074
```

That is **MurmurHash3 x86 32-bit of the field name, UTF-8, seed 0** — verified
against 1,939 of the 1,953 field names published by the community editor. Once
you know that, a field name becomes a testable hypothesis instead of a 32-bit
number you have to guess.

How that was established, including the eight hash functions that produced
exactly zero matches and the brute-force pass that recovered 55 keys and none of
them real, is written up in [`docs/DISCOVERY.md`](docs/DISCOVERY.md).

This project is built on both facts: it edits *all* slots *and* the working
copy in one command, and it resolves any field by name.

---

## Install

No dependencies beyond the standard library.

```bash
git clone https://github.com/ZhaowTao/oot-sw2-save
cd oot-sw2-save
python3 -m pip install .
```

For a throwaway install:

```bash
pipx install git+https://github.com/ZhaowTao/oot-sw2-save
```

Being dated matters here: this game shipped in November 2026, so anything older
than that is describing a different game.

---

## Usage

All commands accept either a single `*.sav` file or a whole save directory.
Pointed at a directory, they default to the slot the game would load.

### See which slot is live

```console
$ ootsw2 slots "<save root>"
root     /Users/dawn/Library/Application Support/nxnative/0400486024DEC000
work copy present (6 slot(s))

SLOT    WRITTEN                    SIZE  FIELDS  IN save.work  STATUS
slot_00 2026-11-13 02:11:23      169408   11926          same
slot_01 2026-11-13 02:10:11      169344   11926          same
slot_02 2026-11-13 02:13:47      169504   11926          same
slot_03 2026-11-13 02:11:58      169464   11926          same
slot_04 2026-11-13 02:15:39      169440   11926          same  ACTIVE (game loads this)
slot_05 2026-11-13 02:14:27      169416   11926          same
```

`ootsw2 roots` finds save directories on this machine if you would rather not
type the path.

### Read fields by name

```console
$ ootsw2 get "<save root>" PlayerStatus.DiveDepth PlayerStatus.EquipWeapon PlayerStatus.CurrentRupee
[slot_04 (newest)]
  PlayerStatus.DiveDepth                       9
  PlayerStatus.EquipWeapon                     Weapon_Sword_Master
  PlayerStatus.CurrentRupee                    759
```

Strings are decoded from the payload pool automatically. `--json` is available
on `get`, `list` and `diff`.

### Write a field, everywhere at once

```console
$ ootsw2 set "<save root>" PlayerStatus.DiveDepth 9 --type float --all-slots
backup -> .../0400486024DEC000-save-before-edit-20261113_021930
  slot_00                PlayerStatus.DiveDepth: 1091567616 -> 9.0 (float)
  slot_01                PlayerStatus.DiveDepth: 1091567616 -> 9.0 (float)
  ...
  mirrored save/ -> save.work/
```

`--all-slots` writes every slot **and** mirrors into `save.work/`, which is the
only way to be sure the game will see the change. A backup of `save/` is taken
first unless you pass `--no-backup`. `--dry-run` shows the plan without touching
anything.

### Compare two saves

```console
$ ootsw2 diff slot_04/progress.sav /tmp/progress-before.sav --named-only
7 field(s) differ
KIND    FIELD                         BEFORE           AFTER
changed PlayerStatus.DiveDepth                6               9
changed PlayerStatus.Life                    44              48
changed PlayerStatus.CurrentRupee           666             759
```

This is the intended way to map the ~83 % of fields that still have no name:
change exactly one thing in game, diff the two saves, and whatever single field
moved is the one you are looking for. Then confirm the name with `probe`.

### Test a field name

```console
$ ootsw2 probe "<save root>" PlayerStatus.DiveDepth PlayerStatus.SwimSpeed
probing slot_04 (newest) (11926 fields)
  hit    PlayerStatus.DiveDepth                               9  (float)
  miss   PlayerStatus.SwimSpeed

1/2 present
```

`probe` hashes the name and checks the table, so you can test a guess without
ever loading an editor. Exit code is `0` if anything hit, `2` if nothing did.

### Browse the dictionary

```console
$ ootsw2 names --prefix PlayerStatus.
PlayerStatus.AnotherEraEquipShield
PlayerStatus.AnotherEraEquipWeapon
PlayerStatus.CurrentRupee
PlayerStatus.DiveDepth
PlayerStatus.EquipArmor
PlayerStatus.EquipBoot
PlayerStatus.EquipHeadArmor
PlayerStatus.EquipOcarina
PlayerStatus.EquipShield
PlayerStatus.EquipWeapon
PlayerStatus.Life
PlayerStatus.LiftGrade
PlayerStatus.MaxLife
PlayerStatus.MPMax
PlayerStatus.NayruLoveTime
...
```

---

## Library

```python
from ootsw2 import SaveFile, SaveDirectory, field_id

# one file
save = SaveFile("slot_04/progress.sav")
print(save.get_float("PlayerStatus.DiveDepth"))      # 9.0
print(save.get_str("PlayerStatus.EquipArmor"))       # 'Armor_Adult_Zora'
save.set_float("PlayerStatus.DiveDepth", 6.0)
save.save()

# the whole directory, all six slots plus the working copy
directory = SaveDirectory("/path/to/0400486024DEC000")
saves = directory.open_all()
for slot in saves.values():
    slot.set_int("PlayerStatus.CurrentRupee", 500)
directory.save_all(saves)                # writes + mirrors save.work
```

`SaveFile` keeps the original bytes verbatim and patches value words in place,
so a field you did not touch is byte-identical to the input. File length does not
change unless you write a longer string.

---

## What is in the box

| | |
|---|---|
| `ootsw2/container.py` | the container: table, payload, string pool, in-place writes |
| `ootsw2/hash.py` | MurmurHash3-32 and the name → key derivation |
| `ootsw2/savedir.py` | the six rotating slots, the `save.work` mirror, backups |
| `ootsw2/fields.py` | the dictionary, with a self-check against the hash |
| `ootsw2/cli.py` | the commands above |
| [`docs/FORMAT.md`](docs/FORMAT.md) | the full format write-up, including what is still unknown |
| [`docs/DISCOVERY.md`](docs/DISCOVERY.md) | the debugging log: how the hash was found, and the four wrong answers before it |

The dictionary ships **1,984 field names**, of which 1,970 satisfy
`field_id(name) == key` — they are self-verifying, not copied on trust.
`ootsw2 verify-dict` prints the 14 that do not, all of them legacy
`<Dungeon>.SmallKeyNum` aliases whose real names are still unknown.

---

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -q          # 51 tests, no game data needed
```

The tests build synthetic containers from scratch, so they run anywhere and
never touch a real save. If you run them inside a vendor Python that injects a
`sitecustomize` shim, clear `PYTHONPATH` first — `env -u PYTHONPATH python3 -m pytest`.

---

## Honest limits

* **Quit the game before editing.** A running game overwrites the directory on
  exit.
* **Most fields are still unnamed.** Roughly 83 % of a `progress.sav` has no
  known name. They are not reachable by brute force: hashing 9.2 million
  plausible combinations drawn from the game's own string table recovered fewer
  than 60, and most of those were coincidences.
* **The type of a value is inferred, not stored.** The file has no type tags.
  Numbers and payload offsets are told apart heuristically (see
  `docs/FORMAT.md` §4.2). The heuristic is correct on every named field so far,
  and `--type` overrides it.
* **Adding a field is supported but unverified.** The table has spare entries and
  `SaveFile.add()` will fill one; only fields the game already writes have been
  confirmed to take effect.
* **Not tested on hardware.** Everything here was validated by editing a save and
  observing the change in a running copy of the game, but the game was running
  through a native recompilation layer, not on a Switch 2 console. The container
  format itself is the game's, so it should carry over; the paths and the
  `save.work` behaviour are host-side.

---

## Credits and legal

* Initial field-name list: [`Traiver/OOT-SW2SE`](https://github.com/Traiver/OOT-SW2SE)
  (MIT). Its table is a hard-coded list of `[key, type, name]` triples; the hash
  relation in `ootsw2/hash.py` is not in it, and that derivation is what makes
  name resolution possible here.
* Format documentation and the remaining names: reverse-engineered for this
  project from save files and from observing the game's own writes.

This project ships **no game code, no game assets and no save files**, and it is
not affiliated with Nintendo. Edit your own saves, on your own copy, and keep a
backup.

MIT licensed — see [LICENSE](LICENSE).

---

[中文说明](README.zh-CN.md)
