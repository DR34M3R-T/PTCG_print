import yaml
import os
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from deck_card import DeckData

conf = None
with open("./conf.yaml") as f:
    conf = yaml.load(f, Loader=yaml.FullLoader)
auto_mask = Image.open("./bleed_frame/mask.png").convert("L").resize((conf['card_w'], conf['card_h']), Image.Resampling.BICUBIC)

def threshold(p):
    if p < 255:
        return 0
    else:
        return 255
    
def auto_bleed(pic: Image.Image):
    # 自动生成出血边框，返回Image对象。
    # 出血框复制图像边缘的非透明像素，扩展到出血区域。
    bleed_frame = Image.new("RGBA", (conf['bleed_w'], conf['bleed_h']), (255, 255, 255, 0))
    
    minbias = min(conf['card_x'], conf['card_y'])
    pic = pic.resize((conf['card_w'], conf['card_h']), Image.Resampling.BICUBIC).convert("RGBA")
    pic.putalpha(auto_mask)

    # 截取pic左上角38x38区域，放大至出血区域左上角
    corner = pic.crop((0, 0, conf['corner_size'], conf['corner_size']))
    for d in range(conf['corner_size'] + minbias, conf['corner_size'],-2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (conf['corner_size'] + conf['card_x'] - d, conf['corner_size'] + conf['card_y'] - d), _corner)
    # 截取pic右上角38x38区域，放大至出血区域右上角
    corner = pic.crop((conf['card_w'] - conf['corner_size'], 0, conf['card_w'], conf['corner_size']))
    for d in range(conf['corner_size'] + minbias, conf['corner_size'],-2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (conf['bleed_w'] - conf['corner_size'] - conf['card_x'], conf['corner_size'] + conf['card_y'] - d), _corner)
    # 截取pic左下角38x38区域，放大至出血区域左下角
    corner = pic.crop((0, conf['card_h'] - conf['corner_size'], conf['corner_size'], conf['card_h']))
    for d in range(conf['corner_size'] + minbias, conf['corner_size'],-2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (conf['corner_size'] + conf['card_x'] - d,  conf['bleed_h'] - conf['corner_size'] - conf['card_y']), _corner)
    # 截取pic右下角38x38区域，放大至出血区域右下角
    corner = pic.crop((conf['card_w'] - conf['corner_size'], conf['card_h'] - conf['corner_size'], conf['card_w'], conf['card_h']))
    for d in range(conf['corner_size'] + minbias, conf['corner_size'],-2):
        _corner = corner.resize((d, d), Image.Resampling.BICUBIC)
        bleed_frame.paste(_corner, (conf['bleed_w'] - conf['corner_size'] - conf['card_x'], conf['bleed_h'] - conf['corner_size'] - conf['card_y']), _corner)
        
    # 上边框
    line = pic.crop((conf['corner_size'], 2, conf['card_w'] - conf['corner_size'], 3)) 
    for y in range(conf['card_y'] + 2):
        bleed_frame.paste(line, (conf['card_x'] + conf['corner_size'], y))
    # 下边框
    line = pic.crop((conf['corner_size'], conf['card_h'] - 3, conf['card_w'] - conf['corner_size'], conf['card_h'] - 2))
    for y in range(conf['card_y'] + conf['card_h'] - 2 , conf['bleed_h']):
        bleed_frame.paste(line, (conf['card_x'] + conf['corner_size'], y))
    # 左边框
    line = pic.crop((2, conf['corner_size'], 3, conf['card_h'] - conf['corner_size']))
    for x in range(conf['card_x'] + 2):
        bleed_frame.paste(line, (x, conf['card_y'] + conf['corner_size']))
    # 右边框
    line = pic.crop((conf['card_w'] - 3, conf['corner_size'], conf['card_w'] - 2, conf['card_h'] - conf['corner_size']))
    for x in range(conf['card_x'] + conf['card_w'] - 2, conf['bleed_w']):
        bleed_frame.paste(line, (x, conf['card_y'] + conf['corner_size']))

    return bleed_frame

def draw(deck: DeckData, bar, label, window):
    page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")
    pos_x = [conf["x11"] + conf["cut_w"] + conf["bleed_w"] * i for i in range(3)]
    pos_y = [conf["y11"] + conf["cut_h"] + conf["bleed_h"] * i for i in range(3)]
    page_pose = [(x, y) for y in pos_y for x in pos_x]
    pos_index = 0
    page_num = 1
    card_count = 0
    dpi = (conf["dpi"], conf["dpi"])
    dir_exist = os.path.exists(f"./out/{deck.name}")
    if not dir_exist:
        os.mkdir(f"./out/{deck.name}")
    font = ImageFont.truetype("simhei.ttf", size=40)
    marker_pos = [
        (conf["card_x"]-conf["cut_w"]+conf["marker_bias"], conf["card_y"]-conf["cut_h"]+conf["marker_bias"]),
        (conf["card_x"]-conf["cut_w"] + conf["card_w"]-conf["marker_bias"], conf["card_y"]-conf["cut_h"]+conf["marker_bias"]),
        (conf["card_x"]-conf["cut_w"]+conf["marker_bias"], conf["card_y"]-conf["cut_h"]+conf["card_h"]-conf["marker_bias"]),
        (conf["card_x"]-conf["cut_w"] + conf["card_w"]-conf["marker_bias"], conf["card_y"]-conf["cut_h"]+conf["card_h"]-conf["marker_bias"])
    ]
    for card in deck.list:
        if card.bleed_id == "z_auto":
            card.pic_with_frame = auto_bleed(Image.open(BytesIO(card.pic))).resize((conf['bleed_w'], conf['bleed_h']), Image.Resampling.BICUBIC)
        else:
            card.pic_with_frame = Image.open(
                f"./bleed_frame/{card.region}/{card.bleed_id}.png"
            )
        _foo = card.pic_with_frame.copy()
        _card = Image.open(BytesIO(card.pic)).convert("RGBA")
        if _card.width != conf["card_w"] or _card.height != conf["card_h"]:
            _card = _card.resize(
                (conf["card_w"], conf["card_h"]), Image.Resampling.BICUBIC
            )
        card.pic_with_frame.paste(_card, (conf["card_x"], conf["card_y"]), _card)
        if card.bleed_id == "z_auto":
            card.pic_with_frame.paste(_foo, (0,0), _foo)
        card.pic_with_frame = card.pic_with_frame.crop(
            (
                conf["cut_w"],
                conf["cut_h"],
                conf["bleed_w"] - conf["cut_w"],
                conf["bleed_h"] - conf["cut_h"],
            )
        )
        if conf['marker'] and card.bleed_id == "z_auto":
            for pos in marker_pos:
                # 检查pos位置处像素亮度
                r, g, b, a = card.pic_with_frame.getpixel(pos)
                brightness = (r + g + b) / 3
                if brightness < 128:
                    marker_color = (255, 255, 255, 255)
                else:
                    marker_color = (0, 0, 0, 255)
                # 在pos位置处绘制一个半径为2的圆点
                picwithframe_draw = ImageDraw.Draw(card.pic_with_frame)
                picwithframe_draw.ellipse(
                    (
                        pos[0] - 2,
                        pos[1] - 2,
                        pos[0] + 2,
                        pos[1] + 2,
                    ),
                    fill=marker_color,
                )
        for i in range(card.num):
            page.paste(card.pic_with_frame, page_pose[pos_index])
            card_count += 1
            bar["value"] = card_count / deck.sum * 100
            label.config(text=f"{card_count}/{deck.sum}")
            pos_index += 1
            if pos_index == 9:
                info_draw = ImageDraw.Draw(page)
                info_draw.text(
                    (page_pose[6][0], page_pose[6][1] + conf["bleed_h"] + 10),
                    deck.loadtime,
                    fill=(0, 0, 0),
                    font=font,
                )
                info_draw.text(
                    (
                        int(conf["A4_w"] / 2 - 200),
                        page_pose[6][1] + conf["bleed_h"] + 10,
                    ),
                    deck.name,
                    fill=(0, 0, 0),
                    font=font,
                )
                info_draw.text(
                    (
                        page_pose[8][0] + conf["bleed_w"] - 50,
                        page_pose[8][1] + conf["bleed_h"] + 10,
                    ),
                    str(page_num),
                    fill=(0, 0, 0),
                    font=font,
                )
                page.save(f"./out/{deck.name}/{page_num}.png", dpi=dpi)
                page_num += 1
                pos_index = 0
                page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")
    if pos_index != 0:
        info_draw = ImageDraw.Draw(page)
        info_draw.text(
            (page_pose[6][0], page_pose[6][1] + conf["bleed_h"] + 10),
            deck.loadtime,
            fill=(0, 0, 0),
            font=font,
        )
        info_draw.text(
            (int(conf["A4_w"] / 2 - 200), page_pose[6][1] + conf["bleed_h"] + 10),
            deck.name,
            fill=(0, 0, 0),
            font=font,
        )
        info_draw.text(
            (
                page_pose[8][0] + conf["bleed_w"] - 50,
                page_pose[8][1] + conf["bleed_h"] + 10,
            ),
            str(page_num),
            fill=(0, 0, 0),
            font=font,
        )
        page.save(f"./out/{deck.name}/{page_num}.png", dpi=dpi)
        draw_back(pos_index, deck.name)
    if card_count >= 9:
        draw_back(9, deck.name)
    deck.update_database()
    label.config(text="Finished!")
    window.protocol("WM_DELETE_WINDOW", lambda: window.destroy())
    pass


def draw_back(n: int, deckname: str):
    if n > 9 or n < 1:
        return
    with open("./conf.yaml") as f:
        conf = yaml.load(f, Loader=yaml.FullLoader)
    page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")
    pos_x = [conf["x11"] + conf["cut_w_back"] + conf["bleed_w"] * i for i in range(3)]
    pos_y = [conf["y11"] + conf["cut_h_back"] + conf["bleed_h"] * i for i in range(3)]
    page_pose = [(x, y) for y in pos_y for x in pos_x]
    pos_index = 0
    page_num = 1
    card_count = 0
    dpi = (conf["dpi"], conf["dpi"])
    font = ImageFont.truetype("simhei.ttf", size=40)
    back = Image.open(f"./bleed_frame/cardback.png").transpose(0)
    back = back.crop(
        (
            conf["cut_w_back"],
            conf["cut_h_back"],
            conf["bleed_w"] - conf["cut_w_back"],
            conf["bleed_h"] - conf["cut_h_back"],
        )
    )
    for i in range(n):
        page.paste(back, page_pose[pos_index])
        card_count += 1
        pos_index += 1
    page = page.transpose(0)
    page.save(f"./out/{deckname}/back{n}.png", dpi=dpi)
    page_num += 1
    pos_index = 0
    page = Image.new("RGB", (conf["A4_w"], conf["A4_h"]), color="#fff")
    pass
