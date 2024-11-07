import requests
import os
import re
import json
import datetime

class CardData:
    with open('./temp/bleed_database.json','r',encoding='utf-8') as f:
        Bleed_Database = json.load(f)
        f.close()
    index_reverse = {v:k for k,v in Bleed_Database['index'].items()}

    def save_database():
        with open('./temp/bleed_database.json','w',encoding='utf-8') as f:
            json.dump(CardData.Bleed_Database,f)
            f.close()

    def __init__(self, raw: str) -> None:
        self.num = 0
        self.name = ''
        self.pack = ''
        self.id = 0
        self.url = 'https://limitlesstcg.nyc3.digitaloceanspaces.com/tpci/'
        self.filename = ''
        self.pic = None
        self.bleed_id = None
        self.pic_with_frame = None
        self.parse(raw)
        
    def parse(self, raw: str):
        try:
            if raw[0]=='#': return -1
            words = raw.split(' ')
            assert len(words)>=4
            self.num = int(words[0])
            if (words[-1] == "PH") : words.pop()
            self.pack = words[-2]
            self.id = words[-1].rjust(3,"0")
            self.name = ' '.join(words[1:-2])
            self.url += f'{self.pack}/{self.pack}_{self.id}_R_EN.png'
            self.filename = f'{self.pack}_{self.id}_R_EN.png'
            _tmp = CardData.Bleed_Database['database'].get(f'{self.pack}_{self.id}') 
            self.bleed_id = 'sv_light' if _tmp is None else CardData.Bleed_Database['index'][f'{_tmp}']
            return 1
        except:
            return -1
    
    def update_database(self):
        CardData.Bleed_Database['database'][f'{self.pack}_{self.id}'] = int(CardData.index_reverse[self.bleed_id])
        
    def download(self):
        try:
            cached = os.path.exists(f'./temp/{self.filename}')
            if cached:
                _f = open(f'./temp/{self.filename}','rb')
                self.pic = _f.read()
                _f.close()
            else:
                self.pic = requests.get(self.url).content
                _f = open(f'./temp/{self.filename}','wb')
                _f.write(self.pic)
                _f.close()
            return 1
        except:
            return -1
        
class DeckData:
    def __init__(self, deck:str) -> None:
        self.sum = 0
        self.list = []
        now = datetime.datetime.now()
        self.name = now.strftime("%y-%m-%d_%H-%M-%S")
        self.loadtime = self.name
        self.__load(deck)
        
    def __load(self,deck):
        try:
            deck = deck.split('\n')
            if deck[0][:9] == "Deckname:":
                _t = deck.pop(0)
                self.name = _t[10:].strip()
                _name_check = re.match('[-\u4e00-\u9fa5_\w\s]{1,50}',self.name)
                assert _name_check.regs[0][1] - _name_check.regs[0][0]==len(self.name)
            for line in deck:
                card = CardData(raw=line)
                if card.num==0:
                    continue
                self.sum += card.num
                self.list.append(card)
        except Exception as e:
            raise Exception('Not a valid Deck')
    
    def update_database(self):
        for card in self.list:
            card.update_database()
        CardData.save_database()
        
if __name__ == "__main__":
    pass
# r = requests.get()