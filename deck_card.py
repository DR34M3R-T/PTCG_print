import os
import re
import datetime
import json
import requests
import pandas as pd
from numpy import isnan
from bs4 import BeautifulSoup as BS


class CardInfo:
    def __init__(self) -> None:
        self.region = ""
        self.pack = ""
        self.id = 0
        self.url = ""
        self.filename = ""
        self.bleed_id = None
        pass

    def getname(self):
        return f"{self.pack}_{self.id}"


class CardData:
    with open("./database/bleed_id.json", "r", encoding="utf-8") as f:
        bleed_id_dict = json.load(f)
        f.close()
    bleed_id_reverse = {
        region: {v: k for k, v in data.items()}
        for region, data in bleed_id_dict.items()
    }
    region = "en-US"
    dtypes = {"id": "str", "group": "int", "bleed_id": "str"}
    database = {
        "en-US": pd.read_csv("./database/en_data.csv", index_col=0, dtype=dtypes),
        "ja-JP": pd.read_csv("./database/ja_data.csv", index_col=0, dtype=dtypes),
        "zh-HK": pd.read_csv("./database/zh_data.csv", index_col=0, dtype=dtypes),
    }
    en_url_pref = "https://limitlesstcg.nyc3.digitaloceanspaces.com/tpci/"
    ja_url_pref = "https://limitlesstcg.nyc3.digitaloceanspaces.com/tpc/"
    zh_url_pref = "https://asia.pokemon-card.com/hk/card-img"

    def save_database():
        CardData.database["en-US"].to_csv("./database/en_data.csv", encoding="utf-8")
        CardData.database["ja-JP"].to_csv("./database/ja_data.csv", encoding="utf-8")
        CardData.database["zh-HK"].to_csv("./database/zh_data.csv", encoding="utf-8")

    def __init__(self, raw: str) -> None:
        self.num = 0
        self.group = -1
        self.pic = None
        self.pic_with_frame = None
        self.alts = {"en-US": [], "ja-JP": [], "zh-HK": []}
        self.current = 0
        self.parse(raw)

    def parse(self, raw: str):
        try:
            if raw[0] == "#":
                return -1
            words = raw.split(" ")
            assert len(words) >= 4
            self.num = int(words[0])
            if words[-1] == "PH":
                words.pop()
            info = CardInfo()
            info.region = "en-US"
            info.pack = words[-2]
            info.id = words[-1]
            str_id = words[-1].rjust(3, "0")
            self.name = " ".join(words[1:-2])
            info.url = f"{self.en_url_pref}{info.pack}/{info.pack}_{str_id}_R_EN.png"
            info.filename = f"{info.pack}_{str_id}_R_EN.png"
            _tmp = CardData.database[info.region].query(
                f'pack == "{info.pack}" and id == "{info.id}"'
            )
            self.group = _tmp["group"].values[0]
            _bleed = str(_tmp["bleed_id"].values[0])
            info.bleed_id = (
                "sv_light"
                if not _bleed.isnumeric()
                else CardData.bleed_id_dict[info.region][_bleed]
            )
            self.alts["en-US"].append(info)
            return 1
        except:
            return -1

    def expand_current(self):
        try:
            tmp_ = self.alts[self.region][self.current]
        except:
            self.region = "en-US"
            tmp_ = self.alts[self.region][self.current]
        for attr_name in tmp_.__dict__:
            if not attr_name.startswith("__"):  # 排除特殊方法和属性
                self.__setattr__(attr_name, tmp_.__getattribute__(attr_name))

    def get_alts(self):
        base = self.alts["en-US"][0]
        en_ingroup = CardData.database["en-US"].query(f"group == {self.group}")
        for index, row in en_ingroup.iterrows():
            if row["pack"] == base.pack and row["id"] == base.id:
                continue
            info = CardInfo()
            info.region = "en-US"
            info.pack = row["pack"]
            info.id = str(row["id"])
            str_id = info.id.rjust(3, "0")
            info.url = f"{self.en_url_pref}{info.pack}/{info.pack}_{str_id}_R_EN.png"
            info.filename = f"{info.pack}_{str_id}_R_EN.png"
            _bleed = str(row["bleed_id"])
            info.bleed_id = (
                "sv_light"
                if not _bleed.isnumeric()
                else CardData.bleed_id_dict[info.region][_bleed]
            )
            self.alts["en-US"].append(info)
        ja_ingroup = CardData.database["ja-JP"].query(f"group == {self.group}")
        for index, row in ja_ingroup.iterrows():
            info = CardInfo()
            info.region = "ja-JP"
            info.pack = row["pack"]
            info.id = str(row["id"])
            info.url = f"{self.ja_url_pref}{info.pack}/{info.pack}_{info.id}_R_JP.png"
            info.filename = f"{info.pack}_{info.id}_R_JP.png"
            _bleed = str(row["bleed_id"])
            info.bleed_id = (
                "sv_light"
                if not _bleed.isnumeric()
                else CardData.bleed_id_dict[info.region][_bleed]
            )
            self.alts["ja-JP"].append(info)
        zh_ingroup = CardData.database["zh-HK"].query(f"group == {self.group}")
        for index, row in zh_ingroup.iterrows():
            info = CardInfo()
            info.region = "zh-HK"
            info.pack = row["pack"]
            info.id = str(row["id"])
            info.filename = row["filename"]
            info.url = f"{self.zh_url_pref}/{info.filename}"
            _bleed = str(row["bleed_id"])
            info.bleed_id = (
                "sv_light"
                if not _bleed.isnumeric()
                else CardData.bleed_id_dict[info.region][_bleed]
            )
            self.alts["zh-HK"].append(info)
        pass

    def get_prints(self):
        l = []
        for card in self.alts[self.region]:
            l.append(card.getname())
        return l

    def update_database(self):
        CardData.database[self.region].loc[
            CardData.database[self.region]
            .query(f'pack == "{self.pack}" and id == "{self.id}"')
            .index,
            "bleed_id",
        ] = CardData.bleed_id_reverse[self.region][self.bleed_id]
        pass

    def download(self):
        try:
            cached = os.path.exists(f"./temp/{self.filename}")
            if cached:
                _f = open(f"./temp/{self.filename}", "rb")
                self.pic = _f.read()
                _f.close()
            else:
                self.pic = requests.get(self.url).content
                _f = open(f"./temp/{self.filename}", "wb")
                _f.write(self.pic)
                _f.close()
            return 1
        except:
            return -1


class DeckData:
    def __init__(self, deck: str, region: str = "en-US") -> None:
        self.sum = 0
        self.list = []
        now = datetime.datetime.now()
        self.region = region
        CardData.region = region
        self.name = now.strftime("%y-%m-%d_%H-%M-%S")
        self.loadtime = self.name
        self.__load(deck)

    def __load(self, deck):
        try:
            deck = deck.split("\n")
            if deck[0][:9] == "Deckname:":
                _t = deck.pop(0)
                self.name = _t[10:].strip()
                _name_check = re.match(r"[-\u4e00-\u9fa5_\w\s]{1,50}", self.name)
                assert _name_check.regs[0][1] - _name_check.regs[0][0] == len(self.name)
            for line in deck:
                card = CardData(raw=line)
                if card.num == 0:
                    continue
                self.sum += card.num
                self.list.append(card)
        except Exception as e:
            raise Exception("Not a valid Deck or Deckname")

    def update_database(self):
        for card in self.list:
            card.update_database()
        CardData.save_database()


if __name__ == "__main__":
    pass
# r = requests.get()
