#!/usr/bin/env python3
"""Render the six slot thumbnails as one contact sheet.

    python3 examples/load_screen_sheet.py "<save root>" docs/img/load-screen.jpg

This is the image the game's own Load screen would show you, one row per slot,
with the label the slot carries in ``caption.sav`` rather than the file name.
It exists mostly because a picture of six saves explains the six-slot rotation
faster than the sentence that describes it.

Needs Pillow (``pip install pillow``); the library itself does not.
"""

import os
import sys

from ootsw2.savedir import SaveDirectory, read_thumbnail

FONT = "/System/Library/Fonts/SFNSMono.ttf"
COLUMNS = 2
PAD = 16
LABEL = 30
BACKGROUND = (17, 17, 19)
FOREGROUND = (240, 240, 240)


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    root, target = argv[1], argv[2]

    from PIL import Image, ImageDraw, ImageFont

    directory = SaveDirectory(root)
    tiles = []
    for slot in directory.slots():
        blob = read_thumbnail(slot.caption_path) if slot.caption_path else None
        if blob is None:
            continue
        caption = slot.caption
        label = "{:<8}{:<18}{:<8}{}".format(
            slot.label,
            (caption.saved_at or "-") if caption else "-",
            (caption.kind or "-") if caption else "-",
            (caption.location or "-") if caption else "-",
        )
        import io

        tiles.append((Image.open(io.BytesIO(blob)).convert("RGB"), label))

    if not tiles:
        raise SystemExit("no thumbnails found")

    width, height = tiles[0][0].size
    rows = (len(tiles) + COLUMNS - 1) // COLUMNS
    sheet = Image.new(
        "RGB",
        (COLUMNS * width + (COLUMNS + 1) * PAD,
         rows * (height + LABEL) + (rows + 1) * PAD),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(FONT, 15)

    for index, (image, label) in enumerate(tiles):
        column = index % COLUMNS
        row = index // COLUMNS
        x = PAD + column * (width + PAD)
        y = PAD + row * (height + LABEL + PAD)
        sheet.paste(image, (x, y))
        draw.text((x + 2, y + height + 7), label, font=font, fill=FOREGROUND)

    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    sheet.save(target, quality=82, optimize=True)
    print("{}  {}x{}  {:.0f} KB  ({} slots)".format(
        target, sheet.width, sheet.height,
        os.path.getsize(target) / 1024, len(tiles)))


if __name__ == "__main__":
    main(sys.argv)
