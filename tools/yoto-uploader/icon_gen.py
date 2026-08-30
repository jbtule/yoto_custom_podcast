"""
16x16 pixel-icon generator for Yoto MYO cards.

Ported from the 3x5 bitmap font, color palettes, and two-line layout of
https://github.com/bettin/yoto-podcast-icons (MIT licensed) -- credit to
its author for the original design.

Adapted for this project's layout, which differs from the source tool's
"season / episode" convention because episodes here are grouped into
*cards* (not seasons), and long episodes get split into two tracks:

  Row 1 (y=2):  "S1.3" -- season number, then card number, in one fixed
                color for the whole season: the podcast config picks one
                named palette per podcast, and the season number indexes
                into that palette's color list (season 1 = colors[0],
                season 2 = colors[1], ...), so every card within one
                season matches, different seasons of the same podcast
                are still distinct, and different podcasts read as
                distinct via their own palette. Assumes single-digit
                season and card numbers (true for how many cards a
                season ever splits into here).
  Row 2 (y=9):  "E" + 2-digit episode number, in white.
  Bottom row:   split-episode marker, in amber -- blank for the first half
                (looks the same as an unsplit episode), a half-width line
                for the second half.

16x16, transparent background (Yoto's own recommendation -- avoid pure
black, which won't show on the player's screen).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

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
    "S": [[1, 1, 1], [1, 0, 0], [1, 1, 1], [0, 0, 1], [1, 1, 1]],
    "C": [[1, 1, 1], [1, 0, 0], [1, 0, 0], [1, 0, 0], [1, 1, 1]],
    "E": [[1, 1, 1], [1, 0, 0], [1, 1, 0], [1, 0, 0], [1, 1, 1]],
    ".": [[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 1, 0]],
    " ": [[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
}

# All 8 named palettes from the source project (bettin/yoto-podcast-icons),
# ported verbatim. Each podcast/season in podcasts.yaml picks one by name
# via its `icon_palette` field, so different shows/seasons read as visually
# distinct at a glance.
PALETTES: dict[str, list[str]] = {
    "original": [
        "#4A90D9", "#50C878", "#E74C3C", "#F39C12", "#9B59B6",
        "#1ABC9C", "#E91E63", "#FF6F00", "#00BCD4", "#8BC34A",
        "#795548", "#607D8B", "#FFEB3B", "#7B1FA2", "#00897B",
        "#FF5722", "#3949AB", "#F48FB1", "#00ACC1", "#AFB42B",
    ],
    "cmyk": [
        "#00AADD", "#DD0077", "#DDCC00", "#00AA77", "#7700AA",
        "#DD6600", "#0077DD", "#AA0055", "#00DD99", "#DD3388",
        "#009999", "#BB4400", "#6600CC", "#AADD00", "#DD0044",
        "#0055AA", "#CC7700", "#880088", "#00CC66", "#DD5599",
    ],
    "cmyk_bright": [
        "#00CCFF", "#FF00CC", "#FFCC00", "#00FF88", "#8800FF",
        "#FF6600", "#0088FF", "#CC0066", "#88DD00", "#FF3399",
        "#00FFCC", "#FF4400", "#5500FF", "#CCFF00", "#FF0066",
        "#0044FF", "#FF9900", "#AA00FF", "#00FF44", "#FF0099",
    ],
    "warm": [
        "#E74C3C", "#FF6F00", "#F39C12", "#FFD600", "#E91E63",
        "#FF5252", "#FF8F00", "#D84315", "#F06292", "#FFAB40",
        "#C62828", "#E65100", "#F9A825", "#FFD740", "#AD1457",
        "#FF1744", "#EF6C00", "#BF360C", "#EC407A", "#FFC400",
    ],
    "cool": [
        "#2196F3", "#00BCD4", "#009688", "#4CAF50", "#7C4DFF",
        "#1DE9B6", "#3F51B5", "#00E5FF", "#69F0AE", "#651FFF",
        "#1565C0", "#00838F", "#00695C", "#2E7D32", "#4527A0",
        "#00BFA5", "#283593", "#0091EA", "#00C853", "#AA00FF",
    ],
    "pastel": [
        "#7EB8DA", "#82CA9D", "#E88E8E", "#F0C674", "#B094D0",
        "#7ECAC5", "#E088A8", "#D9A86C", "#88C8D0", "#A8D08D",
        "#A0C4E8", "#9ED4B0", "#F0A8A0", "#F5D590", "#C8AEE0",
        "#98D8D0", "#F0A0B8", "#E4C08E", "#A0D8E0", "#B8E0A0",
    ],
    "neon": [
        "#00E5FF", "#00FF66", "#FF1744", "#FFEA00", "#D500F9",
        "#00E676", "#FF4081", "#FF9100", "#18FFFF", "#76FF03",
        "#00B0FF", "#00FFAA", "#FF3D00", "#FFD600", "#E040FB",
        "#64FFDA", "#FF80AB", "#FFAB00", "#84FFFF", "#B2FF59",
    ],
    "rainbow": [
        "#FF0044", "#FF3300", "#FF6600", "#FF9900", "#FFCC00",
        "#DDEE00", "#88DD00", "#00CC22", "#00CC66", "#00CCAA",
        "#00CCDD", "#0099FF", "#0055FF", "#0000FF", "#4400DD",
        "#7700BB", "#AA0099", "#DD0077", "#FF0055", "#FF0033",
    ],
}
DEFAULT_PALETTE = "original"

PART_MARKER_COLOR = (255, 204, 0, 255)  # amber -- matches the split-progress line

ICON_SIZE = 16


def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255


def season_color(palette: str, season: int) -> tuple[int, int, int, int]:
    """One fixed color for the whole season's labels -- consistent across
    every card in that season. `season` indexes into the podcast's own
    palette (season 1 = colors[0], season 2 = colors[1], ...), wrapping
    around via modulo if a podcast somehow runs past the palette's 20
    colors, so different seasons of the same podcast are still visually
    distinct from each other."""
    colors = PALETTES.get(palette, PALETTES[DEFAULT_PALETTE])
    return _hex_to_rgba(colors[(season - 1) % len(colors)])


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


def _draw_season_card_line(pixels, season: int, card_num: int, y: int, color: tuple[int, int, int, int]):
    """Draw "S<season>.<card>" as 4 glyphs: S, one digit, ., one digit.
    Assumes single-digit season/card numbers (fits 4 glyphs in 16px)."""
    chars = ["S", str(season % 10), ".", str(card_num % 10)]
    for i, ch in enumerate(chars):
        _draw_char(pixels, ch, i * 4, y, color)


def generate_icon(season: int, card_num: int, episode_num: int, part: int | None = None,
                   palette: str = DEFAULT_PALETTE) -> Image.Image:
    """Build one 16x16 RGBA icon.

    part: None for a whole/unsplit episode, or 1/2 to mark which half of a
    split episode this track is -- 1 looks the same as unsplit (blank), 2
    gets a half-width amber line along the bottom row.
    palette: name of an entry in PALETTES (unknown names fall back to
    DEFAULT_PALETTE); `season` picks which color within it (see
    season_color).
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    pixels = img.load()

    _draw_season_card_line(pixels, season, card_num, 2, season_color(palette, season))
    _draw_line(pixels, "E", episode_num, 9, (255, 255, 255, 255))

    if part == 2:
        for x in range(0, 8):
            pixels[x, 15] = PART_MARKER_COLOR

    return img


def save_icon(season: int, card_num: int, episode_num: int, path: str, part: int | None = None,
              palette: str = DEFAULT_PALETTE):
    generate_icon(season, card_num, episode_num, part=part, palette=palette).save(path, "PNG")


def render_badge(season: int, card_num: int, palette: str = DEFAULT_PALETTE, scale: int = 8) -> Image.Image:
    """Render "S<season>.<card>" as a badge for compositing onto cover
    art: pixel-font text at `scale`x, on a rounded semi-opaque dark chip
    so it stays legible over arbitrary artwork."""
    text_w, text_h = 15, 5  # matches _draw_season_card_line's 4-glyph layout
    small = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    pixels = small.load()
    _draw_season_card_line(pixels, season, card_num, 0, season_color(palette, season))
    big_text = small.resize((text_w * scale, text_h * scale), resample=Image.NEAREST)

    pad = scale
    badge_w, badge_h = big_text.width + pad * 2, big_text.height + pad * 2
    chip = Image.new("RGBA", (badge_w, badge_h), (17, 17, 17, 210))
    mask = Image.new("L", (badge_w, badge_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, badge_w - 1, badge_h - 1], radius=pad, fill=255)
    badge = Image.new("RGBA", (badge_w, badge_h), (0, 0, 0, 0))
    badge = Image.composite(chip, badge, mask)
    badge.paste(big_text, (pad, pad), big_text)
    return badge


# Best guess at the app's card-list crop: full height kept, width
# trimmed to this fraction of height (matches the physical MYO card's
# real proportions, 85.6mm x 54mm => height/width ~= 1.585). Unconfirmed
# exact value from Yoto, but the padding below only ever costs a soft
# blurred border if the guess is off -- it never crops real art.
GUESSED_CROP_HEIGHT_TO_WIDTH_RATIO = 1.585


def _edge_color(cover: Image.Image) -> tuple[int, int, int]:
    """Average of the four corner pixels -- a decent guess at a cover's
    background color for art with a plain border (common for podcast
    cover art), without needing to understand the image's content."""
    w, h = cover.size
    corners = [cover.getpixel((0, 0)), cover.getpixel((w - 1, 0)),
               cover.getpixel((0, h - 1)), cover.getpixel((w - 1, h - 1))]
    return tuple(sum(c[i] for c in corners) // 4 for i in range(3))


def pad_to_safe_portrait(cover: Image.Image, target_ratio: float = GUESSED_CROP_HEIGHT_TO_WIDTH_RATIO) -> Image.Image:
    """Fit `cover` (typically square) into a canvas at `target_ratio`
    (height/width) without cropping any of it: the full image is scaled
    to fit inside, centered, and the leftover space is filled with a
    solid color sampled from the art's own corners (blends in for the
    plain-background-bordered art typical of podcast covers) rather than
    a flat guessed color or (worse) left for the app to crop into. If the
    app's actual crop ratio differs from our guess, the cost is a
    slightly-off solid border -- never lost content, since nothing
    outside this function's own control ever crops the real art.
    """
    cover = cover.convert("RGB")
    w, h = cover.size
    canvas_w, canvas_h = w, round(w * target_ratio)
    if canvas_h <= h:
        return cover  # already tall enough relative to width

    canvas = Image.new("RGBA", (canvas_w, canvas_h), _edge_color(cover) + (255,))
    canvas.paste(cover, (0, (canvas_h - h) // 2))
    return canvas


def apply_cover_badge(cover: Image.Image, season: int, card_num: int, palette: str = DEFAULT_PALETTE) -> Image.Image:
    """Return a copy of `cover` with a season.card badge composited on.

    Placed horizontally centered, near the top: the app is known to crop
    the cover's left/right edges to a narrower (portrait) shape for
    display, keeping full height, so a centered badge stays inside the
    visible area regardless of exactly how wide that crop ends up.
    """
    cover = cover.convert("RGBA")
    scale = max(4, cover.width // 45)  # badge ~35% of cover width
    badge = render_badge(season, card_num, palette=palette, scale=scale)
    margin = badge.height // 2
    x = (cover.width - badge.width) // 2
    y = margin
    out = cover.copy()
    out.alpha_composite(badge, (x, y))
    return out
