"""
16x16 pixel-icon generator for Yoto MYO cards.

Ported from the 3x5 bitmap font, color palette, and two-line layout of
https://github.com/bettin/yoto-podcast-icons (MIT licensed) -- credit to
its author for the original design.

Adapted for this project's layout, which differs from the source tool's
"season / episode" convention because episodes here are grouped into
*cards* (not seasons), and long episodes get split into two tracks:

  Row 1 (y=2):  "C" + 2-digit card number, colored per card so cards are
                easy to tell apart at a glance (cycles through the same
                20-color palette the source project uses for seasons).
  Row 2 (y=9):  "E" + 2-digit episode number, in white.
  Corner pixel: track title's a second-half split ("Part 2")? then a
                single amber pixel is set at (15, 0) as a "continued"
                marker. Part 1 / unsplit episodes have no marker.

16x16, transparent background (Yoto's own recommendation -- avoid pure
black, which won't show on the player's screen).
"""
from __future__ import annotations

from PIL import Image

# 3x5 bitmap font -- each entry is 5 rows x 3 cols of 0/1.
FONT: dict[str, list[list[int]]] = {
    "0": [[1, 1, 1], [1, 0, 1], [1, 0, 1], [1, 0, 1], [1, 1, 1]],
    "1": [[0, 1, 0], [1, 1, 0], [0, 1, 0], [0, 1, 0], [1, 1, 1]],
    "2": [[1, 1, 1], [0, 0, 1], [1, 1, 1], [1, 0, 0], [1, 1, 1]],
    "3": [[1, 1, 1], [0, 0, 1], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    "4": [[1, 0, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1], [0, 0, 1]],
    "5": [[1, 1, 1], [1, 0, 0], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    "6": [[1, 1, 1], [1, 0, 0], [1, 1, 1], [1, 0, 1], [1, 1, 1]],
    "7": [[1, 1, 1], [0, 0, 1], [0, 0, 1], [0, 1, 0], [0, 1, 0]],
    "8": [[1, 1, 1], [1, 0, 1], [1, 1, 1], [1, 0, 1], [1, 1, 1]],
    "9": [[1, 1, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    "C": [[1, 1, 1], [1, 0, 0], [1, 0, 0], [1, 0, 0], [1, 1, 1]],
    "E": [[1, 1, 1], [1, 0, 0], [1, 1, 0], [1, 0, 0], [1, 1, 1]],
    " ": [[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
}

# The source project's "original" 20-color palette -- distinct saturated
# hues, cycled here per card number instead of per season.
PALETTE = [
    "#4A90D9", "#50C878", "#E74C3C", "#F39C12", "#9B59B6",
    "#1ABC9C", "#E91E63", "#FF6F00", "#00BCD4", "#8BC34A",
    "#795548", "#607D8B", "#FFEB3B", "#7B1FA2", "#00897B",
    "#FF5722", "#3949AB", "#F48FB1", "#00ACC1", "#AFB42B",
]

PART_MARKER_COLOR = (255, 204, 0, 255)  # amber -- matches the "Part 2" marker

ICON_SIZE = 16


def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255


def card_color(card_num: int) -> tuple[int, int, int, int]:
    return _hex_to_rgba(PALETTE[(card_num - 1) % len(PALETTE)])


def _pad2(n: int) -> str:
    return f"{n:02d}" if n < 100 else str(n)[-2:]


def _draw_char(pixels, ch: str, x: int, y: int, color: tuple[int, int, int, int]):
    glyph = FONT.get(ch)
    if not glyph:
        return
    for row in range(5):
        for col in range(3):
            if glyph[row][col]:
                pixels[x + col, y + row] = color


def _draw_line(pixels, letter: str, num: int, y: int, color: tuple[int, int, int, int]):
    digits = _pad2(num)
    _draw_char(pixels, letter, 2, y, color)
    _draw_char(pixels, digits[0], 7, y, color)
    _draw_char(pixels, digits[1], 11, y, color)


def generate_icon(card_num: int, episode_num: int, part: int | None = None) -> Image.Image:
    """Build one 16x16 RGBA icon.

    part: None for a whole/unsplit episode, or 1/2 to mark which half of a
    split episode this track is (2 gets a small "continued" corner pixel).
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    pixels = img.load()

    _draw_line(pixels, "C", card_num, 2, card_color(card_num))
    _draw_line(pixels, "E", episode_num, 9, (255, 255, 255, 255))

    if part == 2:
        pixels[15, 0] = PART_MARKER_COLOR

    return img


def save_icon(card_num: int, episode_num: int, path: str, part: int | None = None):
    generate_icon(card_num, episode_num, part=part).save(path, "PNG")
