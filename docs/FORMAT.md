# Save file format

Everything below was derived by reading actual save files produced by
*The Legend of Zelda: Ocarina of Time* on Nintendo Switch 2 (title id
`0400486024DEC000`) and confirming each claim against the game itself: a
value written to disk shows up in game, a value the game writes shows up on
disk. Where something is still a guess it is marked **unconfirmed**.

The order in which these conclusions were reached — and the wrong ones that
came first — is in [`DISCOVERY.md`](DISCOVERY.md).

---

## 1. Directory layout

The game owns a directory tree. On a macOS host running the game through a
native recompilation layer it looks like this:

```
<save root>/
├── account.sav          320 B    profile-wide
├── option.sav            42 KB   options, dialogue language
├── slot_00/
│   ├── progress.sav      ~169 KB  the actual playthrough
│   └── caption.sav      ~32-42 KB one Load-screen entry: clock, place, thumbnail
├── ...
└── slot_05/
```

Next to the directory the engine keeps a **working copy**:

```
<save root>.work/   (named `save.work` inside the title folder)
```

Two things follow from this layout, and both of them are why "I edited the
save and nothing happened" is the single most common failure:

### 1.1 The game rotates through six slots

Every save writes to a *different* slot. Observed sequence from one session:

| wall clock | slot written |
|---|---|
| 00:21:25 | slot_01 |
| 00:22:43 | slot_00 |
| 00:28:26 | slot_03 |
| 01:18:41 | slot_05 |
| 01:25:15 | slot_04 |
| 01:25:29 | slot_02 |

It is not a strict round-robin, but it does move, and **loading picks exactly
one of them** — the most recently written one. A tool that edits a single
`progress.sav` is therefore right about one sixth of the time.

"Most recently written" is the game's own clock in `caption.sav` (§4.4), not the
file mtime. Observed on one directory: five autosaves landed on `slot_00`,
`slot_01`, `slot_03`, `slot_04`, `slot_05` and one manual save on `slot_02` — so
six slots do get used, and a pair of them can share the same minute.

### 1.2 The engine mounts the working copy, not `save/`

While the game runs, the save filesystem it sees is `save.work`, described by
the host layer as *"transactional save: work directory, swapped in atomically on
Commit"*. On save the working copy is swapped back over `save/`.

Consequence: editing `save/` while the game is running can be discarded
wholesale on the next commit, and a stale `save.work` left behind by an
unclean exit can win over a correct `save/`.

**Practical rule:** quit the game, edit *every* slot, and mirror the result
into `save.work` as well. `ootsw2 set --all-slots` does exactly that.

---

## 2. Container format

All four file kinds share one container. `progress.sav` is just the big one.

```
offset  size  meaning
0       4     magic    0x01020304   (little-endian bytes 04 03 02 01)
4       4     version  0x002D80EB
8       4     header_end            offset where the key/value table ends
12      28    reserved, zero
40      -     key/value table
header_end    typed payload: fixed-size records, see §4.2
```

### 2.1 Key/value table

Entry size is **8 bytes**: a 32-bit key followed by a 32-bit value.

```
40 + 8*i :  u32 key     murmur3_32(field name), see §3
40 + 8*i+4: u32 value   inline scalar or payload offset, see §4
```

The table is a fixed-capacity array. Entries whose key is `0` are unused; the
game grows into them and, once they run out, starts appending *payload* data
rather than growing the table. Reading a table therefore means skipping zeros,
not stopping at the first one.

Field counts observed on one playthrough:

| file | header_end | table capacity | live fields | payload |
|---|---|---|---|---|
| `account.sav` | 0x140 | 35 | ~30 | 0 B |
| `option.sav` | 0x2A0 | 79 | ~60 | ~41 KB |
| `caption.sav` | 0x2A0 | 79 | ~47 | ~40 KB |
| `progress.sav` | 0x175D8 | 11 958 | 11 926 | ~73 KB |

`progress.sav` grows by 16 bytes per save (two new fields). The table boundary
stays put; only the payload grows.

There is **no checksum and no signature**. Rewriting a value word in place is
enough, and byte length does not change.

### 2.2 Why the table stays a fixed size

Because values that do not fit in 32 bits are not stored inline — they live in
the payload. Growing the table would shift every payload offset, so the file
format avoids it.

---

## 3. Key derivation

A key is the MurmurHash3 x86 32-bit hash of the field name, UTF-8, seed 0:

```python
field_id("PlayerStatus.DiveDepth")               # 1632005153
field_id("PouchData.Item_Scale_Gold.StockNum")   # 1256920074
```

This was established by taking the 1,953 names published by the community save
editor and hashing each one: **1,939 of them match the key observed on disk**.
Getting 99.3 % agreement is not a coincidence, and the implementation matches
the reference MurmurHash3 test vectors exactly (`""` → 0, `"hello"` →
`0x248BFA47, ...`), so no variant or seed is involved.

The 14 that do *not* match are all of the form `<Dungeon>.SmallKeyNum`. Those
keys are real (they are present in the file) but were not produced from that
name — the name is a guess by the community editor and the true internal name is
unknown. They are carried verbatim in `ootsw2/data/fields.json`, and
`ootsw2 verify-dict` lists them.

### 3.1 Field names are hierarchical strings

Names are dotted paths assembled by the game, for example:

```
PlayerStatus.CurrentRupee
PlayerStatus.DiveDepth
PlayerStatus.EquipWeapon
PlayerStatus.AnotherEraEquipShield
PouchData.Item_Scale_Gold.StockNum
PouchData.BottleA.StockNum
MiniGame_Fishing_GetGoldScale
HaveTalked_Special.<...>
```

The binary contains the templates `PouchData.%s.StockNum` and
`PlayerStatus.AssignableItem.BottleInfo.%s.BottleItem`, which is direct evidence
that these strings are built at runtime rather than stored as a flat list.

Because the derivation is known, a name is a *testable hypothesis*:
`ootsw2 probe` computes the key for any candidate and reports whether it exists
in the file. That is how `PlayerStatus.DiveDepth` was found, and it is the tool
you want for mapping the remaining unnamed fields.

### 3.2 One thing, two fields

Some state is recorded twice, in two fields with different jobs, and editing the
visible one changes nothing that matters.

| looks like the ability | is the ability |
|---|---|
| `PouchData.Item_Scale_Gold.StockNum` — a gold scale in the pouch | `PlayerStatus.DiveDepth` — actually permits 9 m |

| looks like the item | is the record of acquiring it |
|---|---|
| `PouchData.Armor_Child_Mask_Bunny.StockNum` | `IsGet.Armor_Child_Mask_Bunny` |

A normal playthrough proves they are independent: after selling the Bunny Hood,
the game itself writes `IsGet = 1` with `StockNum = 0` — obtained, no longer
carried. Setting `StockNum = 1` on a mask the save has no `IsGet` for leaves an
item the game never recorded acquiring, and the mask shop's story, which runs off
`HappyMaskShop_FirstTimeTalk`, `HappyMaskShop_RentedMaskChoice` and
`IsAfterSell_Mask_Bunny`, stops matching its own state.

Two consequences, both learned the hard way:

* a change you can see in a menu is not a change that took effect;
* removing an item is two writes, not one.

---

## 4. Value encoding

A value word is one of two things.

### 4.1 Inline scalar

Small integers and single-precision floats are stored directly.

```
PlayerStatus.CurrentRupee   666         0x0000029A
PlayerStatus.Life            48         0x00000030    (12 hearts x 4)
PlayerStatus.DiveDepth        9.0f      0x41100000
```

Floats are IEEE-754 single precision, little-endian. Because `9.0f` is
`0x41100000` (1,091,567,616) a float is usually identifiable by being a large
word that decodes to a sane float.

### 4.2 Payload record (fixed-size)

A value that is not an inline scalar is an **absolute offset into the file** at
which a fixed-size record starts. Records are not variable-length and there is
no tag byte in front of them.

| record | size | written by |
|---|---|---|
| `String64` | 64 B | NUL-padded UTF-8 identifier |
| `String32` | 32 B | NUL-padded UTF-8 identifier |
| `Vector3` | 12 B | three `float32` |
| array of 4 | 260 B | `u32` count (4), then 4 × 64 B slots |

The sizes come from the game's own save schema as read by the recompilation
layer's OoT tooling ([`seedds/nxnative` #2002](https://github.com/seedds/nxnative/pull/2002),
`HEADER_END` / `SIZE` in `scripts/ocarina_test_save.py`), and they are confirmed
here on real saves:

* Every string-valued field in `progress.sav` except one sits on a **64-byte
  grid** — offsets 112004, 112068, (112132 empty), 112196 … Gaps of 128 bytes are
  an unused slot in the middle, which is why the pool looks sparse.
* The single exception was a field holding `167280`: a large integer whose value
  lands inside the payload, where the byte at that offset is `0x56` (`"V"`). It
  was a false positive of the reader, not a record. The reader now requires at
  least four characters, because the shortest real entry in six slots is 11
  characters (`HyruleField`).
* `caption.sav` ends in a **543×306 JPEG** (`FF D8 FF` at offset 1396 in every
  slot on this build), which is the thumbnail the Load screen draws.

Field by field:

| field | word | record at that offset |
|---|---|---|
| `PlayerStatus.EquipWeapon` | 112772 | `Weapon_Sword_Master` |
| `PlayerStatus.EquipShield` | 112068 | `Weapon_Shield_Hylian` |
| `PlayerStatus.EquipBoot` | — | `Armor_Adult_HeavyBoot` |
| `PlayerStatus.EquipArmor` | — | `Armor_Adult_Zora` |
| `PlayerStatus.EquipHeadArmor` | — | `Armor_Child_Mask_Truth` |
| `PlayerStatus.EquipOcarina` | — | `Item_Ocarina_Time` |

There is **no type tag** in the file. The game knows the type from its own
schema. A reader has to infer it, and the only reliable discriminator found so
far is:

> If the word lies inside the payload region and the bytes there form a
> printable, uppercase-initial, NUL-terminated ASCII string of at least four
> characters, treat it as an offset to a string record; otherwise treat it as an
> inline scalar.

That heuristic is what `ootsw2.container.is_inline_scalar` implements. It is
correct on every field the dictionary names, and it is the reason the CLI shows
`PlayerStatus.EquipArmor  Armor_Adult_Zora` instead of `112004`.

### 4.3 Writing a string

Replacing a string with one of the same length or shorter overwrites it in
place. A longer string is appended to the payload and the offset is repointed;
the file grows by a few bytes, which is exactly what the game itself does.
Neither operation disturbs any other field, because nothing else points into
that particular slot.

### 4.4 `caption.sav`: what the Load screen shows

Each slot's `caption.sav` is the record the Load menu draws. Same container,
79 table entries, and these are the ones that matter:

| field | id | type | meaning |
|---|---|---|---|
| location name | `0xF74E0E8E` | `String64` | `HyruleField`, `KakarikoVillage`, `TimeTemple` … |
| stage path | `0x0CCCC6CD` | `String64` | `Folder/Stage`, e.g. `KakarikoVillage/KakarikoVillage_Child` |
| autosave flag | `0x25F03CAA` | `u32` | `1` autosave, `0` manual save |
| clock | `0x9811A3F7` … `0x27853BF7` | 5 × `u32` | year, month, day, hour, minute |
| save position | `0x8B26618E` | `Vector3` | where the caption's map pin goes |

The clock is the game's own, minute resolution, and it is the honest answer to
"which slot is newest". File mtimes are only a proxy: copying a save tree or
restoring a backup rewrites them. `ootsw2 slots` prints the game clock, the
autosave flag and the location, and says so when the two orderings disagree.

After the strings the file carries a **JPEG thumbnail**, `543×306`, starting at
`FF D8 FF` — offset 1396 in every slot on this build. It is why `caption.sav`
sizes differ from slot to slot (31.8 KB – 42.1 KB) even though the table is
identical.

The layout of the file is exactly two things, and nothing else:

```
0      .. 1396   the container: header, 79-entry key table, string payload
1396   .. EOF    a complete JPEG, SOI to EOI, with no trailing bytes
```

Checked on all six slots: the end marker `FF D9` is the last two bytes of the
file in every one (`file size - 2`), so the thumbnail can be copied out by
slicing from the first `FF D8` to EOF without decoding anything. That is what
`ootsw2 thumb` does; it writes the same bytes the game writes, not a re-encode.

---

## 5. Editing safely

In order:

1. **Quit the game.** A running game flushes its in-memory state over the
   directory on exit, discarding anything written underneath it. `ootsw2 slots`
   warns if something wrote to the tree in the last 30 seconds.
2. **Back up `save/`.** `ootsw2 set --all-slots` does this by default.
3. **Edit every slot**, not one. Otherwise the game may load a slot you did not
   touch.
4. **Mirror into `save.work`.** Otherwise a stale working copy can win.
5. **Do not change file length unless you mean to.** In-place value edits keep
   the length identical, which is the lowest-risk change.

---

## 6. What is still unknown

* **The arrays and the packed integers at the start of the payload.** The
  payload is not only string records: it opens with packed small integers
  (looks like counts and index lists) and about 310 field values point into it,
  of which only a minority land on a string. The record sizes are known (§4.2)
  but the *meaning* of most of these blocks is not. *Unconfirmed.*
* **Why the string pool starts 44 bytes off a 64-byte boundary.** The pool
  itself is 64-byte aligned (§4.2), but the region before it is a whole number of
  64-byte records plus 44 bytes. Not explained.
* **The true names of 11,926 − 1,972 fields.** Roughly 83 % of a
  `progress.sav` is unnamed. They are not enumerable by brute force: hashing
  9.2 million plausible combinations out of the game's own string table
  recovered fewer than 60, most of them coincidences.
* **The 14 `<Dungeon>.SmallKeyNum` aliases.** Keys are real, names are not.
* **Whether a newly added field is honoured.** The table has spare entries and
  `ootsw2 add` can fill one, but only fields the game already knows about have
  been verified to take effect.
* **How the Load list is ordered when two slots share a minute.** The clock in
  `caption.sav` has minute resolution, so a tie has to be broken by something
  else — file order, slot index, or a second counter that was not found.

## 6.1 Sources for the block sizes

The record sizes in §4.2 and the three fields that decide where a load puts Link
(`Sequence_CurrentBanc`, `PlayerStatus.SavePos`, `PlayerStatus.SavePosRadY`) were
published independently in [`seedds/nxnative` #2002](https://github.com/seedds/nxnative/pull/2002)
(`scripts/ocarina_test_save.py`), which also credits Traiver's field catalog for
the hash. Two things were checked here rather than taken on trust:

1. **The hash constants.** All eleven named fields in that script hash to
   exactly the ids it declares, using `field_id()` in this repository — an
   independent third confirmation of MurmurHash3 (after the reference test
   vectors and the 1,939/1,953 agreement).
2. **The keys.** `Player_Pos_For_Map` and `Player_Rot_For_Map` were missing from
   this dictionary; both keys are present in all six slots here, so they were
   added. The script's four unnamed ids (`0x874C7ED4` quest step,
   `0x4A6BDB7D` last stage, `0x8773F02D` last position, `0xC458F1EB` location
   array) are likewise present, but carry no name, so they stay reachable by
   numeric id only.

---

## 7. Credits

The initial list of field names came from the community save editor
[`Traiver/OOT-SW2SE`](https://github.com/Traiver/OOT-SW2SE) (MIT). Its table is a
hard-coded list of `[key, type, name]` triples — it does not contain the hash
relation documented in §3, which is what this project adds.

No game code, game assets, or save files are redistributed here.
