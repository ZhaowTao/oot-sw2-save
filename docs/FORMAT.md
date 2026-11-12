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
│   └── caption.sav       41 KB   per-slot Saria's-song / caption state
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
header_end    payload
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

### 4.2 Payload offset (strings)

String-valued fields store an offset into the payload region rather than a
number. At that offset sits a NUL-terminated ASCII string.

| field | word | payload at that offset |
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
> printable, uppercase-initial, NUL-terminated ASCII string, treat it as an
> offset; otherwise treat it as an inline scalar.

That heuristic is what `ootsw2.container.is_inline_scalar` implements. It is
correct on every field the dictionary names, and it is the reason the CLI shows
`PlayerStatus.EquipArmor  Armor_Adult_Zora` instead of `112004`.

### 4.3 Writing a string

Replacing a string with one of the same length or shorter overwrites it in
place. A longer string is appended to the payload and the offset is repointed;
the file grows by a few bytes, which is exactly what the game itself does.
Neither operation disturbs any other field, because nothing else points into
that particular string.

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

* **The payload region beyond strings.** It clearly holds more than a string
  pool — around 310 field values point into it, and not all of those offsets
  land on printable text. Arrays and sets are probably in there.
  *Unconfirmed.*
* **The true names of 11,926 − 1,970 fields.** Roughly 83 % of a
  `progress.sav` is unnamed. They are not enumerable by brute force: hashing
  9.2 million plausible combinations out of the game's own string table
  recovered fewer than 60, most of them coincidences.
* **The 14 `<Dungeon>.SmallKeyNum` aliases.** Keys are real, names are not.
* **Whether a newly added field is honoured.** The table has spare entries and
  `ootsw2 add` can fill one, but only fields the game already knows about have
  been verified to take effect.

---

## 7. Credits

The initial list of field names came from the community save editor
[`Traiver/OOT-SW2SE`](https://github.com/Traiver/OOT-SW2SE) (MIT). Its table is a
hard-coded list of `[key, type, name]` triples — it does not contain the hash
relation documented in §3, which is what this project adds.

No game code, game assets, or save files are redistributed here.
