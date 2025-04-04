import time
import requests
from io import StringIO
from bs4 import BeautifulSoup as BS
import pandas as pd

en_packs = {
    "Sword & Shield Promos": "SP",
    "Sword & Shield": "SSH",
    "Rebel Clash": "RCL",
    "Darkness Ablaze": "DAA",
    "Champion's Path": "CPA",
    "Vivid Voltage": "VIV",
    "Shining Fates": "SHF",
    "Battle Styles": "BST",
    "Chilling Reign": "CRE",
    "Evolving Skies": "EVS",
    "Celebrations": "CEL",
    "Fusion Strike": "FST",
    "Brilliant Stars": "BRS",
    "Astral Radiance": "ASR",
    "Pokémon GO": "PGO",
    "Lost Origin": "LOR",
    "Silver Tempest": "SIT",
    "Crown Zenith": "CRZ",
    "Scarlet & Violet Promos": "SVP",
    "Scarlet & Violet Energy": "SVE",
    "Scarlet & Violet": "SVI",
    "Paldea Evolved": "PAL",
    "Obsidian Flames": "OBF",
    "Pokémon 151": "MEW",
    "Paradox Rift": "PAR",
    "Paldean Fates": "PAF",
    "Temporal Forces": "TEF",
    "Twilight Masquerade": "TWM",
    "Shrouded Fable": "SFA",
    "Stellar Crown": "SCR",
    "Surging Sparks": "SSP",
    "Prismatic Evolutions": "PRE",
    "Journey Together": "JTG",
}
ja_packs = {
    "Hot Wind Arena":"SV9a",
    "ex Starter Set Steven's Beldum & Metagross ex":"SVOD",
    "ex Starter Set Marnie's Morpeko & Grimmsnarl ex":"SVOM",
    "Battle Partners":"SV9",
    "Battle Partners Deck Build Box":"SVN",
    "Terastal Fest ex": "SV8a",
    "Starter Decks Generations": "SVM",
    "Super Electric Breaker": "SV8",
    "Paradise Dragona": "SV7a",
    "Stellar Tera Type Starter Set Sylveon ex": "SVLN",
    "Stellar Tera Type Starter Set Ceruledge ex": "SVLS",
    "Stellar Miracle": "SV7",
    "Stellar Miracle Deck Build Box": "SVK",
    "Night Wanderer": "SV6a",
    "Battle Master Deck Charizard ex": "SVJL",
    "Battle Master Deck Chien-Pao ex": "SVJP",
    "Mask of Change": "SV6",
    "Crimson Haze": "SV5a",
    "Scarlet & Violet: Battle Academy": "SVI",
    "Wild Force": "SV5K",
    "Cyber Judge": "SV5M",
    "Ancient Koraidon ex Starter Deck & Build Set": "SVHK",
    "Future Miradon ex Starter Deck & Build Set": "SVHM",
    "Shiny Treasure ex": "SV4a",
    "Special Deck Set ex Venusaur & Charizard & Blastoise": "SVG",
    "Ancient Roar": "SV4K",
    "Future Flash": "SV4M",
    "Raging Surf": "SV3a",
    "Terastal Starter Set Skeledirge ex": "SVEL",
    "Terastal Starter Set Mewtwo ex": "SVEM",
    "Ruler of the Black Flame": "SV3",
    "Deck Build Box Ruler of the Black Flame": "SVF",
    "World Championships 2023 Yokohama Deck –Pikachu–": "WCS23",
    "ex Starter Decks": "SVD",
    "Pokémon Card 151": "SV2a",
    "ex Special Set": "SVP1",
    "Clay Burst": "SV2D",
    "Snow Hazard": "SV2P",
    "ex Starter Set Pikachu ex & Pawmot": "SVC",
    "Triplet Beat": "SV1a",
    "Scarlet ex": "SV1S",
    "Violet ex": "SV1V",
    "ex Starter Set Fuecoco & Ampharos ex": "SVAL",
    "ex Starter Set Sprigatito & Lucario ex": "SVAM",
    "ex Starter Set Quaxly & Mimikyu ex": "SVAW",
    "Premium Trainer Box ex": "SVB",
    "Scarlet & Violet Promotional Cards": "SVP",
    "VSTAR Universe": "S12a",
    "Special Deck Set: Charizard VSTAR vs Rayquaza VMAX": "SO",
    "Paradigm Trigger": "S12",
    "Incandescent Arcana": "S11a",
    "VSTAR Special Set": "SP6",
    "Lost Abyss": "S11",
    "VSTAR&VMAX High-Class Deck Deoxys": "SPD",
    "VSTAR&VMAX High-Class Deck Zeraora": "SPZ",
    "Pokémon GO": "S10b",
    "Dark Phantasma": "S10a",
    "Time Gazer": "S10D",
    "Space Juggler": "S10P",
    "Starter Deck 100 CoroCoro ver.": "SN",
    "Battle Region": "S9a",
    "Starter Set Darkrai VSTAR": "SLD",
    "Starter Set Lucario VSTAR": "SLL",
    "Star Birth": "S9",
    "VSTAR Premium Trainer Box": "SK",
    "Starter Decks 100": "SI",
    "VMAX Climax": "S8b",
    "Special Deck Set: Zacian & Zamazenta vs Eternatus": "SJ",
    "25th Anniversary Collection": "S8a",
    "Fusion Arts": "S8",
    "V-UNION Special Card Sets": "SP5",
    "Skyscraping Perfection": "S7D",
    "Blue Sky Stream": "S7R",
    "Family Pokémon Card Game": "SML",
    "Eevee Heroes": "S6a",
    "High-Class Deck Gengar VMAX": "SGG",
    "High-Class Deck Inteleon VMAX": "SGI",
    "VMAX Special Set Eevee Heroes": "SP4",
    "Silver Lance": "S6H",
    "Jet-Black Spirit": "S6K",
    "Jumbo-Pack Set Silver Lance & Jet-Black Spirit": "SP3",
    "Matchless Fighters": "S5a",
    "Single Strike Master": "S5I",
    "Rapid Strike Master": "S5R",
    "Premium Trainer Box Single Strike & Rapid Strike": "SF",
    "Charizard VMAX Starter Set 2": "SC2",
    "Venusaur VMAX Starter Set": "SEF",
    "Blastoise VMAX Starter Set": "SEK",
    "Shiny Star V": "S4a",
    "VMAX Special Set": "SP2",
    "Amazing Volt Tackle": "S4",
    "Legendary Heartbeat": "S3a",
    "V Starter Decks": "SD",
    "Infinity Zone": "S3",
    "Explosive Walker": "S2a",
    "Grimmsnarl VMAX Starter Set": "SCd",
    "Charizard VMAX Starter Set": "SCr",
    "Rebel Clash": "S2",
    "VMAX Rising": "S1a",
    "Zacian & Zamazenta Box": "SP1",
    "Shield": "S1H",
    "Sword": "S1W",
    "Premium Trainer Box Sword & Shield": "SB",
    "Starter Set V Fighting": "SAf",
    "Starter Set V Grass": "SAg",
    "Starter Set V Lightning": "SAl",
    "Starter Set V Fire": "SAr",
    "Starter Set V Water": "SAw",
    "Sword & Shield Promotional Cards": "SP",
}

dtypes = {"id": "str", "group": "int", "bleed_id": "str"}
en_data = pd.read_csv('./database/en_data.csv',index_col=0,dtype=dtypes)
ja_data = pd.read_csv('./database/ja_data.csv',index_col=0,dtype=dtypes)
zh_data = pd.read_csv('./database/zh_data.csv',index_col=0,dtype=dtypes)
with open('./database/zh_hidpi.csv', 'r') as file:
    lines = file.readlines()
zh_hidpi_list = [line.strip() for line in lines]

# promo num check
promo_current = en_data.query('pack == "SVP"')
promo_num = len(promo_current)
print(f'en SVP have {promo_num} cards in database.')
promo_pack_url = f"https://limitlesstcg.com/cards/SVP?sort=set&display=list"
retry_counter = 0
while True:
    try:
        pack_page = requests.get(promo_pack_url).content
        break
    except:
        retry_counter+=1
        print(f'pack SVP retrying: x{retry_counter}                             ',end='\r')
        time.sleep(2)
promo_pack_soup = BS(pack_page, "html.parser")
promo_pack_tb = promo_pack_soup.find("table")
promo_pack_tb_IO = StringIO(promo_pack_tb.prettify())
promo_pack_df = pd.read_html(promo_pack_tb_IO)[0]
promo_pack_tb_IO.close()
promo_pack_df = promo_pack_df[["Set", "No.", "Name"]]
promo_pack_df.columns = ["pack", "id", "name"]
promo_pack_df["id"] = promo_pack_df["id"].astype(str)
promo_pack_df["group"] = -1
promo_pack_df["bleed_id"] = ""
promo_pack_delta = promo_pack_df[~promo_pack_df["id"].isin(promo_current["id"])]
print(f'add {len(promo_pack_delta)} promos.')

# update newest en pack
group_idx = en_data['group'].max() + 1
_, pack = list(en_packs.items())[-1]
pack_url = f"https://limitlesstcg.com/cards/{pack}?sort=set&display=list"
retry_counter = 0
while True:
    try:
        pack_page = requests.get(pack_url).content
        break
    except:
        retry_counter+=1
        print(f'pack {pack} retrying: x{retry_counter}                             ',end='\r')
        time.sleep(2)
pack_soup = BS(pack_page, "html.parser")
pack_tb = pack_soup.find("table")
pack_tb_IO = StringIO(pack_tb.prettify())
pack_df = pd.read_html(pack_tb_IO)[0]
pack_tb_IO.close()
pack_df = pack_df[["Set", "No.", "Name"]]
pack_df.columns = ["pack", "id", "name"]
pack_df["id"] = pack_df["id"].astype(str)
pack_df["group"] = -1
pack_df["bleed_id"] = ""
pack_df = pd.concat([promo_pack_delta, pack_df], axis=0).reset_index(drop=True)

for index, row in pack_df.iterrows():
    card_url = f"https://limitlesstcg.com/cards/{row['pack']}/{row['id']}"
    zh_url_suffix = "https://asia.pokemon-card.com/hk/card-search/list/?expansionCodes="
    zh_card_url = ''
    retry_counter = 0
    while True:
        try:
            card_page = requests.get(card_url).content
            break
        except:
            retry_counter+=1
            print(f"card {row['pack']}_{row['id']} retrying: x{retry_counter}",end='\r')
            time.sleep(2)
    print(f"{row['pack']}_{row['id']}                                       ",end='\r')
    card_soup = BS(card_page, "html.parser")
    card_tb = card_soup.find(class_="card-prints-versions").find_all("tr")
    card_tb.pop(0)
    en_flag = False
    ja_flag = False
    is_SVP_init_release = False
    en_print_list = []
    ja_print_list = []
    for tr in card_tb:
        if not ja_flag:
            if "JP. Prints" in tr.text:
                ja_flag = True
                if (row["pack"] == "SVP") and (is_SVP_init_release):
                    row["group"] = group_idx
                    en_data.loc[len(en_data)] = row
                    group_idx += 1
                    is_SVP_init_release=False
                continue
            if en_flag and not is_SVP_init_release:
                continue
            en_pack_full, en_id = list([s.strip() for s in tr.text.split("#")])
            if not (en_pack_full in en_packs.keys()):
                continue
            en_flag = True
            en_pack = en_packs[en_pack_full]
            en_id = en_id.split("\n")[0].strip()
            if en_id == row["id"] and en_pack == row["pack"]:
                if row["pack"] == "SVP":
                    is_SVP_init_release = True
                    continue
                row["group"] = group_idx
                en_data.loc[len(en_data)] = row
                group_idx += 1
                continue
            else:
                group_exist = en_data.query(
                    f'pack == "{en_pack}" and id == "{en_id}"'
                )["group"].values
                if len(group_exist) <= 0:
                    if row["pack"] == "SVP":
                        is_SVP_init_release = True
                        continue
                else:
                    group_exist = group_exist[0]
                    is_SVP_init_release=False
                row["group"] = group_exist
                en_data.loc[len(en_data)] = row
                continue
        if "Show all prints" in tr.text:
            break
        ja_pack_full, ja_id = list([s.strip() for s in tr.text.split("#")])
        if not (ja_pack_full in ja_packs.keys()):
            continue
        ja_pack = ja_packs[ja_pack_full]
        ja_exist = ja_data.query(
            f'pack == "{ja_pack}" and id == "{ja_id}"'
        )
        if (len(ja_exist) <= 0) : 
            jp_new_row = pd.Series([ja_pack,ja_id,row["group"],''],index=ja_data.columns)
            ja_data.loc[len(ja_data)] = jp_new_row
            # zh print add
            if not ja_id.isnumeric(): continue
            ja_id = int(ja_id)
            pagenum = int((ja_id-1)/20)
            id_inpage = ja_id-pagenum*20-1
            old_url = zh_card_url
            zh_card_url = f"{zh_url_suffix}{ja_pack}&pageNo={pagenum+1}"
            retry_counter=0
            while zh_card_url!=old_url:
                try:
                    official_page = requests.get(zh_card_url).content
                    break
                except:
                    retry_counter+=1
                    time.sleep(2)
            soup = BS(official_page,'html.parser')
            try:
                cards = list(soup.find_all(class_ = 'imageContainer'))
                card = cards[id_inpage]
            except:
                continue
            zh_pic_url = card.find('img').attrs['data-original']
            filename = zh_pic_url.split('/')[-1]
            if filename in zh_hidpi_list:
                zh_new_row = pd.Series([ja_pack,str(ja_id),row['group'],filename,''],index=zh_data.columns)
                zh_data.loc[len(zh_data)] = zh_new_row
    pass
pass

ja_trim = pd.DataFrame(columns=["pack", "id", "group", "bleed_id"])

def sort_data(row):
    if row.name == 'pack':
        a = row.map(lambda x: -list(ja_packs.values()).index(x))
    if row.name == 'id':
        a = row.map(lambda x: int(x) if x.isnumeric() else 9999)
    return a

for index, row in ja_data.iterrows():
    if row['pack'] in ja_packs.values():
        ja_trim.loc[len(ja_trim)] = row
    pass
ja_sort = ja_trim.sort_values(by=['pack','id'],key=sort_data).reset_index(drop=True)
zh_sort = zh_data.sort_values(by=['pack','id'],key=sort_data).reset_index(drop=True)
en_data.to_csv('./database/en_data.csv',encoding='utf-8')
ja_sort.to_csv('./database/ja_data.csv',encoding='utf-8')
zh_sort.to_csv('./database/zh_data.csv',encoding='utf-8')
pass