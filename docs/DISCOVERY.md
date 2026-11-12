# How the key derivation was found

This is a debugging log, not a specification. The specification is
[`FORMAT.md`](FORMAT.md); this file records the order things were learned in,
including the four hypotheses that were wrong and why each one looked right at
the time. If you are trying to reverse-engineer a save format yourself, the
wrong turns are the useful part.

Everything here happened on 12–13 November 2026, on save files written by
*The Legend of Zelda: Ocarina of Time* on Nintendo Switch 2 (title id
`0400486024DEC000`).

---

## 0. The symptom

I wanted to unlock the fishing minigame and raise the dive depth. I edited
`PlayerStatus.CurrentRupee` in a save file, booted the game, and the rupee
counter was unchanged. Not "wrong value" — unchanged, exactly as before.

That single observation hides five separate problems, and they are stacked in
the order below. Each layer produced a *different* false conclusion, and every
one of them looked like "the edit didn't work".

---

## 1. Layer 0: a process check that always says "not running"

The obvious first check is whether the game is still running, because a live
process will flush its in-memory state over the directory when it exits.

```console
$ ps aux | grep -c nxnative
0
$ pgrep -f 0400486024DEC000
$
```

Empty output. Conclusion drawn: the game is closed, so nothing can overwrite
the file. That conclusion was wrong — on this machine `ps` and `pgrep` are
restricted and return nothing for these processes. The tool was not broken; it
was answering a different question than the one I asked.

The check that actually works is a file the game writes unconditionally, and
its mtime:

```console
$ f=~/Library/Logs/nxnative/0400486024DEC000.log
$ a=$(stat -f %z "$f"); sleep 3; b=$(stat -f %z "$f"); echo "$a -> $b"
184213 -> 184213     # really closed
184213 -> 187704     # running, and I just edited a file it owns
```

**Rule taken from this:** when a tool can be silently restricted, do not treat
silence as a negative answer. Pick a signal whose *presence* is unambiguous —
a counter that only ever grows — and measure change in it.

---

## 2. Layer 1: six slots, one of which gets loaded

With the game actually closed, edits still did nothing. Watching write times
across one play session gave the answer:

| wall clock | slot written |
|---|---|
| 00:21:25 | `slot_01` |
| 00:22:43 | `slot_00` |
| 00:28:26 | `slot_03` |
| 01:18:41 | `slot_05` |
| 01:25:15 | `slot_04` |
| 01:25:29 | `slot_02` |

Six `progress.sav` files, written in rotation, and loading takes only the most
recent. So "I edited the save" was, with probability 5/6, "I edited a file the
game was never going to read". The edit was correct and irrelevant, which is
why the game showed no change *and* no error.

---

## 3. Layer 2: the engine mounts a different directory

Reading the host layer's own log explained the remaining 1/6:

```
fs mount save:  /…/0400486024DEC000/save.work   (transactional save)
```

While the game runs it mounts a **working copy**. On commit, the working copy is
swapped over `save/` atomically. Editing `save/` under a running game is
therefore not merely risky — it is discarded wholesale at the next commit, and
a stale `save.work` from an unclean exit beats a correct `save/`.

This is the point where a tool stopped being a nice-to-have: writing six slots
*and* mirroring them into the working copy is not something a human should be
asked to remember. `ootsw2 set --all-slots` exists because of this layer.

---

## 4. Layer 3: the field that looks right and does nothing

With all six slots and the working copy written consistently, the rupee
changed. The fishing flags changed. So the mechanism worked.

Then dive depth did not change. The save contained

```
PouchData.Item_Scale_Gold.StockNum = 1
```

which is the gold scale, and the item menu showed it. The dive depth in game
stayed at 6 metres. The field controls *ownership*, not *capability*: the depth
is a separate float, `PlayerStatus.DiveDepth`, and it was sitting at `6.0f`.

```
PlayerStatus.DiveDepth = 6.0f   (0x40C00000)
```

Writing `9.0f` moved the limit to 9 metres immediately. Two thirds of the
apparent failures in this project were of this shape: a field that is real,
present, writable, and not the one that governs the behaviour.

## 4.1 A side note on the numbers

My first attempt set the depth to 12 m, because that is the N64 value for the
silver scale and `zeldaret/oot` contains `D_80854784[] = {120, 240, 360}`
(centimetres). The remake uses **3 / 6 / 9 m**. The value was accepted and
clamped, so the result was 9 — which I initially read as "the write failed".

The remake is not the N64 game, and `zeldaret/oot3d` is a skeleton (its
`Player` file is ~32 lines of placeholder), so there was no decompilation to
read. The numbers came from five independent guide sites agreeing on 3/6/9.

**Rule taken from this:** confirm which build of the game you are looking at
before reasoning from source code. The title id and the binary's own strings
(`Phive/GameDataList/RSDB`, which is a Switch 2 engine marker) settle it in
seconds.

---

## 5. The actual question: what is a key?

The container turned out to be a flat table of 8-byte entries:

```
40 + 8*i  :  u32 key
40 + 8*i+4:  u32 value
```

`progress.sav` holds 11,926 of these. The keys are not sequential and not
sorted, which is the tell that they are hashes of something.

There was an obvious external source of field names: the community save editor
[`Traiver/OOT-SW2SE`](https://github.com/Traiver/OOT-SW2SE) ships a table of
1,953 names, each with a key and a type, as `[key, type, name]` triples. That
table is exactly what a hash is for. Take the names, hash them, compare to the
keys.

### 5.1 Eight algorithms, zero hits

| candidate | hits out of 1,953 |
|---|---|
| CRC-32 | 0 |
| FNV-1 | 0 |
| FNV-1a | 0 |
| djb2 | 0 |
| djb2 (xor) | 0 |
| sdbm | 0 |
| OAT (`hash = h*33 + c`) | 0 |
| xxHash32 | 0 |
| **MurmurHash3 x86-32, seed 0** | **1,939** |

Eight wrong guesses produced *exactly zero* matches each time, which was the
most misleading thing about the whole exercise: 1,953 names against 1,953 keys
collide by accident with probability 1953²/2³² ≈ 0.0009, so "zero hits" is what
you should expect from ~1,100 wrong algorithms out of ~1,100. The metric carried
no information at all. The correct answer is not identifiable by counting alone.

The reason it was found at all is unrelated to the search: MurmurHash3 had
already been implemented locally for a different purpose, and it was the one
function in the toolbox that had never been tried against this data.

### 5.2 Confirming it instead of counting it

1,939 / 1,953 is 99.3 %, and 99.3 % is not proof. Two independent checks settled
it:

1. **The official test vectors.** `""` → `0`, `"hello"` → `0x248BFA47`,
   `"The quick brown fox jumps over the lazy dog"` → `0x2E4FF723`. The
   implementation matches all of them, so no seed, no variant, no byte-order
   difference is involved.
2. **The shape of the 14 misses.** If the algorithm were wrong, the misses
   would be scattered over the name space. All 14 were the same kind of name:

   ```
   DodongoCavern.SmallKeyNum
   BottomOfTheWell.SmallKeyNum
   FinalBattleField.SmallKeyNum
   ...
   ```

   A correct hash plus an incorrect *name guess* produces exactly this: a
   clustered failure on one naming convention, and nowhere else. Those 14 keys
   are real (they are in the file), the names are the community editor's
   invention, and the true internal names are still unknown. They are carried
   verbatim and reported by `ootsw2 verify-dict`.

**Rule taken from this:** a near-perfect match is more informative than a
perfect one. The residuals have a structure, and the structure tells you which
*assumption* is wrong.

---

## 6. The attempt that failed, and why brute force was never going to work

The obvious follow-up to "keys are hashes of names" is "then enumerate names".
The game binary has a string table; combine its words into plausible dotted
paths and hash them.

First pass: 59,118 strings × 12 prefixes × 13 suffixes = **9.22 million hashes
in 43 seconds**. Recovered **55** keys. Most were three-letter coincidences like
`HP`, and none of them were interesting.

Second pass, two-stage (hash every prefix *and* every suffix, then look for
pairs whose combination hits a known key) needs O(n²) combinations — around
3.5 × 10⁹. It did not finish and was killed.

The reason both were doomed is visible in the binary itself:

```
PouchData.%s.StockNum
PlayerStatus.AssignableItem.BottleInfo.%s.BottleItem
```

Field names are **printf templates assembled at runtime**, not a flat list
sitting in the file. Enumerating a list that does not exist is not a search
problem with a bad constant; it is the wrong shape of problem.

What replaced it: since `field_id()` is known, a candidate name is a cheap,
falsifiable hypothesis. `ootsw2 probe "<root>" PlayerStatus.DiveDepth` hashes
the name and checks the table — one question, one answer, no enumeration. That
is how `DiveDepth` was confirmed, and how the remaining unnamed fields should be
attacked: change one thing in game, `diff` the two saves, then confirm the name.

---

## 7. Two bugs made while reading the container

Both were found by the tool disagreeing with the game, not by reading code.

**Stopping at the first zero key.** Unused table entries have key `0`, so the
natural read is "stop at the first zero". It gave a table of 40 entries and a
`progress.sav` with no `CurrentRupee` — because keys are not packed at the front.
The table is a fixed-capacity array with holes, and the game fills the holes
over time. Correct read: skip zeros, do not stop.

**Assuming a type tag.** Values are 32-bit with no tag, and the game knows the
type from its own schema. The first reader printed

```
PlayerStatus.EquipWeapon     112772
```

which is not a weapon. `112772` is an offset, and the bytes at `header_end +
112772` read `Weapon_Sword_Master\0`. The discriminator that works:

> If the word falls inside the payload region **and** the bytes there form a
> printable, NUL-terminated ASCII string, it is an offset; otherwise it is an
> inline scalar.

That heuristic is `is_inline_scalar()`. It is right on every named field so far
and it is explicitly a heuristic — the file gives no way to be certain.

---

## 8. The moment the chain closed

The whole stack was validated by one edit that a person can see:

```
$ ootsw2 set "<root>" PlayerStatus.DiveDepth 9 --type float --all-slots
$ ootsw2 get "<root>" PlayerStatus.DiveDepth
9
```

…and in game, the dive limit went from 6 m to 9 m.

That single result exercises every layer at once: quit-detection, six slots,
working-copy mirror, key hash, value type, and the difference between the field
that looks right and the field that governs behaviour. It is also why the CLI
prints a backup path and a per-slot line for every write — the layer that failed
is not visible from the outside, so the tool has to say what it touched.

---

## 9. Rules worth keeping

1. **Silence is not a negative answer.** Restricted tools return empty, not
   error. Prefer a monotonic signal.
2. **A correct edit to the wrong file has no error message.** If nothing
   changed, the first suspect is which bytes the program reads, not the value.
3. **Confirm the build before trusting a source.** N64 code and a 2026 remake
   disagree on numbers in ways that look like bugs.
4. **Test vectors before expensive experiments.** They are cheap, they are
   independent of the data, and they rule out seed and endianness in seconds.
5. **Read the residuals.** 14 clustered misses proved the algorithm; 55
   scattered hits did not.
6. **If a search needs O(n²), the assumption behind it is wrong.**
   `PouchData.%s.StockNum` was the refutation, and it was in the binary the
   whole time.
7. **Re-derive from behaviour, not from the name of a field.** `StockNum` sounds
   like a capability and is a display.

---

## 10. Reproducing this on another title

The method generalises; the hash probably does not.

1. Find the container: look for a fixed-size header followed by an array of
   8-byte pairs, then a region after it that values point into.
2. Take any published field list for that game and test candidate hashes against
   the keys. Check the implementation against known test vectors **before**
   interpreting the hit count.
3. Look at the misses. Clustering means the algorithm is right and the names are
   wrong; scattering means the algorithm is wrong.
4. Confirm candidate names directly with `probe` rather than enumerating.
5. Map the rest by differential editing: one change in game, one `diff`.

If a title's keys do turn out to be MurmurHash3-32 of the name, `ootsw2/hash.py`
is 30 lines and has no dependencies.

---

## Credits

Field-name list: [`Traiver/OOT-SW2SE`](https://github.com/Traiver/OOT-SW2SE)
(MIT) — 1,953 names as `[key, type, name]` triples, which is what made the hash
searchable at all. That project documents the keys; the relation between keys and
names is what is described above.

No game code, game assets or save files are included in this repository.
