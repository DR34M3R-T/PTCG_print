import yaml
import os
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from deck_card import DeckData

def draw(deck:DeckData, bar, label, window):
    with open('./conf.yaml') as f:
        conf = yaml.load(f,Loader=yaml.FullLoader)
    page = Image.new("RGB",(conf['A4_w'],conf['A4_h']),color='#fff')
    pos_x = [conf['x11']+conf['cut_w']+conf['bleed_w']*i for i in range(3)]
    pos_y = [conf['y11']+conf['cut_h']+conf['bleed_h']*i for i in range(3)]
    page_pose = [(x,y) for y in pos_y for x in pos_x]
    pos_index = 0
    page_num = 1
    card_count = 0
    dpi = (conf['dpi'],conf['dpi'])
    dir_exist = os.path.exists(f'./out/{deck.name}')
    if not dir_exist: os.mkdir(f'./out/{deck.name}')
    font = ImageFont.truetype('simhei.ttf' ,size=40)
    for card in deck.list:
        card.pic_with_frame = Image.open(f'./bleed_frame/{card.bleed_id}.png')
        _card = Image.open(BytesIO(card.pic))
        card.pic_with_frame.paste(_card, (conf['card_x'],conf['card_y']), _card)
        card.pic_with_frame = card.pic_with_frame.crop((
            conf['cut_w'],conf['cut_h'],conf['bleed_w']-conf['cut_w'],conf['bleed_h']-conf['cut_h']
        ))
        for i in range(card.num):
            page.paste(card.pic_with_frame, page_pose[pos_index])
            card_count += 1
            bar['value'] = card_count/deck.sum*100
            label.config(text=f"{card_count}/{deck.sum}")
            pos_index += 1
            if pos_index == 9:
                info_draw = ImageDraw.Draw(page)
                info_draw.text((page_pose[6][0],page_pose[6][1]+conf['bleed_h']+10),deck.loadtime,fill=(0,0,0),font=font)
                info_draw.text((int(conf['A4_w']/2-200),page_pose[6][1]+conf['bleed_h']+10),deck.name,fill=(0,0,0),font=font)
                info_draw.text((page_pose[8][0]+conf['bleed_w']-50,page_pose[8][1]+conf['bleed_h']+10),str(page_num),fill=(0,0,0),font=font)
                page.save(f'./out/{deck.name}/{page_num}.png',dpi=dpi)
                page_num += 1
                pos_index = 0
                page = Image.new("RGB",(conf['A4_w'],conf['A4_h']),color='#fff')
    if pos_index!=0:
        info_draw = ImageDraw.Draw(page)
        info_draw.text((page_pose[6][0],page_pose[6][1]+conf['bleed_h']+10),deck.loadtime,fill=(0,0,0),font=font)
        info_draw.text((int(conf['A4_w']/2-200),page_pose[6][1]+conf['bleed_h']+10),deck.name,fill=(0,0,0),font=font)
        info_draw.text((page_pose[8][0]+conf['bleed_w']-50,page_pose[8][1]+conf['bleed_h']+10),str(page_num),fill=(0,0,0),font=font)
        page.save(f'./out/{deck.name}/{page_num}.png',dpi=dpi)
    deck.update_database()
    label.config(text="Finished!")
    window.protocol("WM_DELETE_WINDOW", lambda: window.destroy())
    pass