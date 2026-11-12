#!/usr/bin/env python3
"""Print the equipment a save has equipped, by name.

    python3 examples/dump_equipment.py "<save root>"

Strings live in the payload pool as game identifiers, so the output is
`Weapon_Sword_Master` rather than "Master Sword" -- that mapping is a display
concern and is not part of the save format.
"""

import sys

from ootsw2 import SaveDirectory

SLOTS = [
    "PlayerStatus.EquipWeapon",
    "PlayerStatus.EquipShield",
    "PlayerStatus.EquipArmor",
    "PlayerStatus.EquipBoot",
    "PlayerStatus.EquipHeadArmor",
    "PlayerStatus.EquipOcarina",
    "PlayerStatus.AnotherEraEquipWeapon",
    "PlayerStatus.AnotherEraEquipShield",
]


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    directory = SaveDirectory(argv[1])
    active = directory.active_slot()
    if active is None:
        print("no slots found", file=sys.stderr)
        return 1

    save = directory.open_slot(active.index)
    print(f"{active.label}  ({len(save)} fields)")
    for name in SLOTS:
        value = save.get_str(name)
        print(f"  {name:<36} {value if value is not None else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
