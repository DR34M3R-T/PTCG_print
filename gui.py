import tkinter as tk
import os
from threading import Thread
from PIL import Image, ImageTk
from tkinter import ttk
from io import BytesIO
from deck_card import DeckData
from layout import draw

def disable_close_button(window):
    # 通过重载wm_protocols方法禁用关闭按钮
    window.protocol("WM_DELETE_WINDOW", lambda: None)


class GUI():
    def __init__(self) -> None:
        self.deck = None

        self.root = tk.Tk()
        self.screen_size = (self.root.winfo_screenwidth(),self.root.winfo_screenheight())
        self.root.geometry(f"320x300+{int(self.screen_size[0]/2-160)}+{int(self.screen_size[1]/2-150)}")
        self.root.resizable(False,False)
        self.root.title('PTCG Layout Generator')
        self.root.iconbitmap('./icon.ico',default='./icon.ico')
        
        self.rootFrame1 = tk.Frame(self.root)
        self.deckBoxLabel = tk.Label(self.rootFrame1,text="Paste your Deck below:")
        self.loadDeckBtn = tk.Button(self.rootFrame1,text="Load Deck...",command=self.load_deck)
        self.deckBox = tk.Text(self.root)
        with open('./deck.txt', 'r', encoding='utf-8') as deckfile:
            _decktxt = deckfile.read()
            self.deckBox.insert(tk.END,_decktxt)
        self.rootFrame1.pack()
        self.deckBoxLabel.pack(side=tk.LEFT, padx=5, pady=5)
        self.loadDeckBtn.pack(side=tk.RIGHT,padx=5)
        self.deckBox.pack(padx=5,pady=5)
        self.root.mainloop()

    def load_deck(self):
        self.deck = DeckData(self.deckBox.get('1.0',tk.END))
        self.picnum = len(self.deck.list)
        self.downloadSubwindow = tk.Toplevel(self.root)
        disable_close_button(self.downloadSubwindow)
        self.downloadSubwindow.grab_set()
        self.downloadSubwindow.geometry(f"300x40+{int(self.screen_size[0]/2-150)}+{int(self.screen_size[1]/2-20)}")
        self.downloadSubwindow.resizable(False,False)
        self.downloadSubwindow.title("Downloading...")
        self.downloadBar = ttk.Progressbar(self.downloadSubwindow,length=210)
        self.downloadLabel = tk.Label(self.downloadSubwindow,text=f"0/{self.picnum}")
        self.downloadBar.pack(side=tk.LEFT, padx=10)
        self.downloadLabel.pack(side=tk.RIGHT, padx=10)
        Thread(target = self.download).start()
        pass

    def download(self):
        for i in range(self.picnum):
            self.deck.list[i].download()
            self.downloadLabel.config(text=f"{i+1}/{self.picnum}")
            self.downloadBar['value'] = (i+1)/self.picnum*100
        self.downloadSubwindow.destroy()
        Thread(target = self.select_bleed).start()
        pass

    def select_bleed(self):
        self.BLEED_FRAME_names = [name[:-4] for name in os.listdir('./bleed_frame/')]
        self.BLEED_FRAMES = dict({name: Image.open(f'./bleed_frame/{name}.png').resize((400,540)) for name in self.BLEED_FRAME_names})
        self.p = 0
        self.bleedSubwindow = tk.Toplevel(self.root)
        self.bleedSubwindow.grab_set()
        self.bleedSubwindow.focus_set()
        self.bleedSubwindow.geometry(f"510x540+{int(self.screen_size[0]/2-255)}+{int(self.screen_size[1]/2-300)}")
        self.bleedSubwindow.resizable(False,False)
        self.bleedSubwindow.title(f"Select bleed frame: {self.p+1}/{self.picnum} x{self.deck.list[self.p].num}")
        self.canvas = tk.Canvas(self.bleedSubwindow,width=400,height=540)

        self._bleed = ImageTk.PhotoImage(self.BLEED_FRAMES[self.deck.list[self.p].bleed_id])
        self.canvas.create_image(0,0,anchor='nw',image=self._bleed)

        _pic = Image.open(BytesIO(self.deck.list[self.p].pic))
        _resized = _pic.resize((368,512))
        self._pic = ImageTk.PhotoImage(_resized)
        self.canvas.create_image(16,14,anchor='nw',image=self._pic)

        self.bleedFrame1 = tk.Frame(self.bleedSubwindow,width=110,height=540)
        self.tipLabel = tk.Label(self.bleedFrame1,text="WASD and arrow\nkeys are enabled\n")
        self.bleedSelectorFrame = tk.Frame(self.bleedFrame1)
        self.bleedSelectorList = []
        self.bleedVar = tk.StringVar()
        for bleed_name in self.BLEED_FRAME_names:
            _tmp = tk.Radiobutton(self.bleedSelectorFrame, text=bleed_name, value=bleed_name, variable=self.bleedVar)
            self.bleedSelectorList.append(_tmp)
        self.bleedVar.set(self.deck.list[self.p].bleed_id)
        self.bleedVar.trace_add('write',self.bleed_change)
        self.bleedFrame2 = tk.Frame(self.bleedFrame1,width=110)
        self.prevpicBtn = tk.Button(self.bleedFrame2,text="←",command=self.prevpic)
        self.nextpicBtn = tk.Button(self.bleedFrame2,text="→",command=self.nextpic)
        self.generateBtn = tk.Button(self.bleedFrame1,text="generate",command=self.gen)
        self.canvas.pack(side=tk.LEFT)
        self.bleedFrame1.pack(side=tk.RIGHT)
        self.tipLabel.pack(anchor=tk.CENTER)
        self.bleedSelectorFrame.pack(anchor=tk.CENTER)
        for radio in self.bleedSelectorList:
            radio.pack(anchor=tk.W)
        self.bleedFrame2.pack(anchor=tk.CENTER)
        self.prevpicBtn.pack(side=tk.LEFT)
        self.nextpicBtn.pack(side=tk.RIGHT)
        self.generateBtn.pack(anchor=tk.CENTER)

        self.bleedSubwindow.bind("<KeyPress>",self.bleed_kbd)
        pass

    def prevpic(self):
        if self.p==0:
            return
        else: 
            self.p-=1
            self.refresh()
            return

    def nextpic(self):
        if self.p==self.picnum-1:
            return
        else: 
            self.p+=1
            self.refresh()
            return
    
    def bleed_polling(self,direction):
        l = len(self.BLEED_FRAME_names)
        i = self.BLEED_FRAME_names.index(self.bleedVar.get())
        i += direction
        if i>=l:
            i -=l
        if i<0:
            i+=l
        self.bleedVar.set(self.BLEED_FRAME_names[i])

    def bleed_change(self,varname,index,mode):
        self.deck.list[self.p].bleed_id = self.bleedVar.get()
        self.refresh()

    def bleed_kbd(self,e):
        match e.keycode:
            case 65 | 37: # left
                self.prevpic()
            case 68 | 39: # right
                self.nextpic()
            case 87 | 38: # up
                self.bleed_polling(-1)
            case 83 | 40: # down
                self.bleed_polling(+1)

    def refresh(self):
        self.bleedVar.set(self.deck.list[self.p].bleed_id)
        self.bleedSubwindow.title(f"Select bleed frame: {self.p+1}/{self.picnum} x{self.deck.list[self.p].num}")

        self._bleed = ImageTk.PhotoImage(self.BLEED_FRAMES[self.deck.list[self.p].bleed_id])
        self.canvas.create_image(0,0,anchor='nw',image=self._bleed)

        _pic = Image.open(BytesIO(self.deck.list[self.p].pic))
        _resized = _pic.resize((368,512))
        self._pic = ImageTk.PhotoImage(_resized)
        self.canvas.create_image(16,14,anchor='nw',image=self._pic)

    def gen(self):
        self.bleedSubwindow.destroy()
        self.drawSubwindow = tk.Toplevel(self.root)
        disable_close_button(self.drawSubwindow)
        self.drawSubwindow.grab_set()
        self.drawSubwindow.geometry(f"300x40+{int(self.screen_size[0]/2-150)}+{int(self.screen_size[1]/2-20)}")
        self.drawSubwindow.resizable(False,False)
        self.drawSubwindow.title("Generating...")
        self.drawBar = ttk.Progressbar(self.drawSubwindow,length=210)
        self.drawLabel = tk.Label(self.drawSubwindow,text=f"0/{self.deck.sum}")
        self.drawBar.pack(side=tk.LEFT, padx=10)
        self.drawLabel.pack(side=tk.RIGHT, padx=10)
        Thread(target=draw, args=(self.deck, self.drawBar, self.drawLabel, self.drawSubwindow)).start()

GUI()