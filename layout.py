from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable

import yaml
from PIL import Image, ImageDraw, ImageFont

from deck_card import DeckData

REPO_ROOT = Path(__file__).resolve().parent
CONF_PATH = REPO_ROOT / "conf.yaml"
BLEED_DIR = REPO_ROOT / "bleed_frame"
OUT_DIR = REPO_ROOT / "out"

with CONF_PATH.open("r", encoding="utf-8") as _f:
    conf: dict = yaml.safe_load(_f)

auto_mask = (
    Image.open(BLEED_DIR / "mask.png")
    .convert("L")
    .resize((conf["card_w"], conf["card_h"]), Image.Resampling.BICUBIC)
)


def _load_font(size: int = 40) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ("simhei.ttf", "msyh.ttc", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def auto_bleed(pic: Image.Image) -> Image.Image:
    """Generate adaptive bleed frame by extending card edge & corner pixels outward."""
    bleed_frame = Image.new("RGBA", (conf["bleed_w"], conf["bleed_h"]), (255, 255, 255, 0))

    minbias = min(conf["card_x"], conf["card_y"])
    pic_rgba = pic.resize((conf["card_w"], conf["card_h"]), Image.Resampling.BICUBIC).convert("RGBA")
    pic_rgba.putalpha(auto_mask)

    cs = conf["corner_size"]
    cx, cy = conf["card_x"], conf["card_y"]
    cw, ch = conf["card_w"], conf["card_h"]
    bw, bh = conf["bleed_w"], conf["bleed_h"]

    # Top-left corner
    corner = pic_rgba.crop((0, 0, cs, cs))
    for d in range(cs + minbias, cs, -2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (cs + cx - d, cs + cy - d), _corner)

    # Top-right corner
    corner = pic_rgba.crop((cw - cs, 0, cw, cs))
    for d in range(cs + minbias, cs, -2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (bw - cs - cx, cs + cy - d), _corner)

    # Bottom-left corner
    corner = pic_rgba.crop((0, ch - cs, cs, ch))
    for d in range(cs + minbias, cs, -2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (cs + cx - d, bh - cs - cy), _corner)

    # Bottom-right corner
    corner = pic_rgba.crop((cw - cs, ch - cs, cw, ch))
    for d in range(cs + minbias, cs, -2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (bw - cs - cx, bh - cs - cy), _corner)

    # Top edge
    line = pic_rgba.crop((cs, 2, cw - cs, 3))
    for y in range(cy + 2):
        bleed_frame.paste(line, (cx + cs, y))

    # Bottom edge
    line = pic_rgba.crop((cs, ch - 3, cw - cs, ch - 2))
    for y in range(cy + ch - 2, bh):
        bleed_frame.paste(line, (cx + cs, y))

    # Left edge
    line = pic_rgba.crop((2, cs, 3, ch - cs))
    for x in range(cx + 2):
        bleed_frame.paste(line, (x, cy + cs))

    # Right edge
    line = pic_rgba.crop((cw - 3, cs, cw - 2, ch - cs))
    for x in range(cx + cw - 2, bw):
        bleed_frame.paste(line, (x, cy + cs))

    return bleed_frame


def compose_card_with_bleed(pic_bytes: bytes, add_markers: bool = True, crop_cut: bool = True) -> Image.Image:
    """Compose a single card image with adaptive auto_bleed, optional crop and cut markers."""
    src = Image.open(BytesIO(pic_bytes)).convert("RGBA")
    frame = auto_bleed(src)
    frame_overlay = frame.copy()

    card_img = src
    if card_img.width != conf["card_w"] or card_img.height != conf["card_h"]:
        card_img = card_img.resize((conf["card_w"], conf["card_h"]), Image.Resampling.BICUBIC)

    frame.paste(card_img, (conf["card_x"], conf["card_y"]), card_img)
    frame.paste(frame_overlay, (0, 0), frame_overlay)

    if crop_cut:
        frame = frame.crop(
            (
                conf["cut_w"],
                conf["cut_h"],
                conf["bleed_w"] - conf["cut_w"],
                conf["bleed_h"] - conf["cut_h"],
            )
        )

    if add_markers and conf.get("marker", False):
        offset_x = conf["card_x"] - (conf["cut_w"] if crop_cut else 0)
        offset_y = conf["card_y"] - (conf["cut_h"] if crop_cut else 0)
        bias = conf.get("marker_bias", -2)
        marker_pos = [
            (offset_x + bias, offset_y + bias),
            (offset_x + conf["card_w"] - bias, offset_y + bias),
            (offset_x + bias, offset_y + conf["card_h"] - bias),
            (offset_x + conf["card_w"] - bias, offset_y + conf["card_h"] - bias),
        ]
        drawer = ImageDraw.Draw(frame)
        for mx, my in marker_pos:
            if 0 <= mx < frame.width and 0 <= my < frame.height:
                r, g, b, _ = frame.getpixel((mx, my))
                brightness = (r + g + b) / 3
                marker_color = (255, 255, 255, 255) if brightness < 128 else (0, 0, 0, 255)
                drawer.ellipse((mx - 2, my - 2, mx + 2, my + 2), fill=marker_color)

    return frame


def _draw_footer(
    page: Image.Image,
    page_pose: list[tuple[int, int]],
    loadtime: str,
    deck_name: str,
    page_num: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    info_draw = ImageDraw.Draw(page)
    footer_y = page_pose[6][1] + conf["bleed_h"] + 10

    info_draw.text((page_pose[6][0], footer_y), loadtime, fill=(0, 0, 0), font=font)

    bbox = info_draw.textbbox((0, 0), deck_name, font=font)
    text_w = bbox[2] - bbox[0]
    info_draw.text((int((conf["A4_w"] - text_w) / 2), footer_y), deck_name, fill=(0, 0, 0), font=font)

    num_str = str(page_num)
    num_bbox = info_draw.textbbox((0, 0), num_str, font=font)
    num_w = num_bbox[2] - num_bbox[0]
    right_x = page_pose[8][0] + (conf["bleed_w"] - 2 * conf["cut_w"]) - num_w
    info_draw.text((right_x, footer_y), num_str, fill=(0, 0, 0), font=font)


def draw(
    deck: DeckData,
    on_progress: Callable[[int, int], None] | None = None,
    on_done: Callable[[Path], None] | None = None,
) -> Path:
    page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")
    pos_x = [conf["x11"] + conf["cut_w"] + conf["bleed_w"] * i for i in range(3)]
    pos_y = [conf["y11"] + conf["cut_h"] + conf["bleed_h"] * i for i in range(3)]
    page_pose = [(x, y) for y in pos_y for x in pos_x]

    pos_index = 0
    page_num = 1
    card_count = 0
    dpi = (conf["dpi"], conf["dpi"])
    deck_out_dir = OUT_DIR / deck.name
    deck_out_dir.mkdir(parents=True, exist_ok=True)
    font = _load_font(40)

    for card in deck.list:
        if not card.pic:
            continue
        card.pic_with_frame = compose_card_with_bleed(card.pic, add_markers=True, crop_cut=True)
        for _ in range(card.num):
            page.paste(card.pic_with_frame, page_pose[pos_index])
            card_count += 1
            if on_progress:
                on_progress(card_count, deck.sum)
            pos_index += 1
            if pos_index == 9:
                _draw_footer(page, page_pose, deck.loadtime, deck.name, page_num, font)
                page.save(deck_out_dir / f"{page_num}.png", dpi=dpi)
                page_num += 1
                pos_index = 0
                page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")

    if pos_index != 0:
        _draw_footer(page, page_pose, deck.loadtime, deck.name, page_num, font)
        page.save(deck_out_dir / f"{page_num}.png", dpi=dpi)
        draw_back(pos_index, deck.name)

    if card_count >= 9:
        draw_back(9, deck.name)

    if on_done:
        on_done(deck_out_dir)

    return deck_out_dir


def draw_back(n: int, deckname: str) -> Path | None:
    if n > 9 or n < 1:
        return None
    page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")
    pos_x = [conf["x11"] + conf["cut_w_back"] + conf["bleed_w"] * i for i in range(3)]
    pos_y = [conf["y11"] + conf["cut_h_back"] + conf["bleed_h"] * i for i in range(3)]
    page_pose = [(x, y) for y in pos_y for x in pos_x]

    dpi = (conf["dpi"], conf["dpi"])
    back = Image.open(BLEED_DIR / "cardback.png").transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    back = back.crop(
        (
            conf["cut_w_back"],
            conf["cut_h_back"],
            conf["bleed_w"] - conf["cut_w_back"],
            conf["bleed_h"] - conf["cut_h_back"],
        )
    )
    for i in range(n):
        page.paste(back, page_pose[i])

    page = page.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    out_path = OUT_DIR / deckname / f"back{n}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.save(out_path, dpi=dpi)
    return out_path
