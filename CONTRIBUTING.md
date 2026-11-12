# Contributing

The most useful contribution right now is **field names**.

## Adding a field name

A field's key is `murmur3_32(name)`, so a name is a hypothesis you can test
without touching an editor:

1. Guess a name, e.g. `PlayerStatus.SwimSpeed`.
2. `ootsw2 probe "<save root>" PlayerStatus.SwimSpeed`
3. If it misses, try another. If it hits, note the value it returns and confirm
   in game that changing it does what you expect.

To record a confirmed name, add it to `ootsw2/data/fields.json` as
`"<Name>": <key>` and run `ootsw2 verify-dict` — the entry must satisfy
`field_id(name) == key` unless it is an explicitly unverified legacy alias.

## Finding unnamed fields

The reliable method is differential:

1. Back up `save/`.
2. Do exactly one thing in game (pick up a heart piece, learn a song, ...).
3. Save, quit.
4. `ootsw2 diff <backup>/slot_XX/progress.sav <save>/slot_XX/progress.sav`

A single thing usually moves one or two fields. Cross-reference which field was
already named to narrow down the namespace, then probe candidates under the same
prefix.

## Rules

* Never commit a save file, a dump of one, or any game asset. `.gitignore`
  blocks `*.sav` for a reason.
* Keep the tests data-free. Build containers with `tests/conftest.build_save`.
* A format claim belongs in `docs/FORMAT.md`; mark anything unproven as
  **unconfirmed**.
