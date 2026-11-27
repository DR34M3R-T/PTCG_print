from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk, PngImagePlugin

from deck_card import REGIONS, DeckData
from layout import compose_card_with_bleed, draw

MaximumDecompressedSize = 1024
MegaByte = 2**20
PngImagePlugin.MAX_TEXT_CHUNK = MaximumDecompressedSize * MegaByte

REPO_ROOT = Path(__file__).resolve().parent


def disable_close_button(window: tk.Toplevel) -> None:
    window.protocol("WM_DELETE_WINDOW", lambda: None)


class GUI:
    def __init__(self) -> None:
        self.deck: DeckData | None = None
        self.p: int = 0
        self.picnum: int = 0
        self._preview_img: ImageTk.PhotoImage | None = None

        self.root = tk.Tk()
        self.screen_size = (
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self.root.geometry(
            f"340x400+{int(self.screen_size[0] / 2 - 170)}+{int(self.screen_size[1] / 2 - 200)}"
        )
        self.root.resizable(False, False)
        self.root.title("PTCG Layout Generator")
        icon_path = REPO_ROOT / "icon.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path), default=str(icon_path))

        self.deckBoxLabel = tk.Label(self.root, text="Paste your Deck below:")
        self.deckBox = tk.Text(self.root, height=23)
        deck_path = REPO_ROOT / "deck.txt"
        if deck_path.exists():
            self.deckBox.insert(tk.END, deck_path.read_text(encoding="utf-8"))

        self.rootFrame1 = tk.Frame(self.root)
        self.regionEnum = list(REGIONS)
        self.regionCombo = ttk.Combobox(self.rootFrame1, state="readonly", width=10)
        self.regionCombo["value"] = self.regionEnum
        self.regionCombo.current(0)

        self.loadDeckBtn = tk.Button(
            self.rootFrame1, text="Load Deck...", command=self.load_deck
        )

        self.deckBoxLabel.pack(anchor=tk.W, padx=6, pady=(6, 2))
        self.deckBox.pack(padx=6, fill=tk.BOTH, expand=True)
        self.rootFrame1.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=8)
        self.regionCombo.pack(side=tk.LEFT, padx=8)
        self.loadDeckBtn.pack(side=tk.RIGHT, padx=8)

        self.root.mainloop()

    def load_deck(self) -> None:
        raw_text = self.deckBox.get("1.0", tk.END)
        preferred_region = self.regionCombo.get()
        try:
            self.deck = DeckData(raw_text, preferred_region)
        except Exception as exc:
            messagebox.showerror("Invalid Deck", str(exc))
            return

        if self.deck.unmatched_lines:
            preview = "\n".join(self.deck.unmatched_lines[:10])
            extra = (
                f"\n... (+{len(self.deck.unmatched_lines) - 10} more)"
                if len(self.deck.unmatched_lines) > 10
                else ""
            )
            messagebox.showwarning(
                "Unmatched Cards",
                f"The following lines were not found in database and skipped:\n\n{preview}{extra}",
            )

        self.picnum = len(self.deck.list)
        self.downloadSubwindow = tk.Toplevel(self.root)
        disable_close_button(self.downloadSubwindow)
        self.downloadSubwindow.grab_set()
        self.downloadSubwindow.geometry(
            f"320x48+{int(self.screen_size[0] / 2 - 160)}+{int(self.screen_size[1] / 2 - 24)}"
        )
        self.downloadSubwindow.resizable(False, False)
        self.downloadSubwindow.title("Downloading...")
        self.downloadBar = ttk.Progressbar(self.downloadSubwindow, length=220)
        self.downloadLabel = tk.Label(self.downloadSubwindow, text=f"0/{self.picnum}")
        self.downloadBar.pack(side=tk.LEFT, padx=10)
        self.downloadLabel.pack(side=tk.RIGHT, padx=10)

        Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self) -> None:
        assert self.deck is not None
        cards = self.deck.list
        total = len(cards)
        done = 0
        failed_cards: list[str] = []

        def prepare_card(card):
            card.get_alts()
            card.expand_current()
            ok = card.download()
            return card, ok

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(prepare_card, c) for c in cards]
            for fut in as_completed(futures):
                card, ok = fut.result()
                done += 1
                if ok != 1:
                    err = f" - {card.last_error}" if card.last_error else ""
                    failed_cards.append(f"{card.name} ({card.pack} {card.id}){err}")
                progress = done / total * 100
                self.root.after(0, self._update_download_progress, done, total, progress)

        self.root.after(0, self._on_download_finished, failed_cards)

    def _update_download_progress(self, done: int, total: int, progress: float) -> None:
        if self.downloadSubwindow.winfo_exists():
            self.downloadLabel.config(text=f"{done}/{total}")
            self.downloadBar["value"] = progress

    def _on_download_finished(self, failed_cards: list[str]) -> None:
        if self.downloadSubwindow.winfo_exists():
            self.downloadSubwindow.destroy()
        if failed_cards:
            messagebox.showwarning(
                "Download Warning",
                "Failed to download some card images:\n\n" + "\n".join(failed_cards[:10]),
            )
        self.open_preview_window()

    def open_preview_window(self) -> None:
        assert self.deck is not None
        self.p = 0
        self.picnum = len(self.deck.list)

        self.previewWindow = tk.Toplevel(self.root)
        self.previewWindow.grab_set()
        self.previewWindow.focus_set()
        self.previewWindow.geometry(
            f"580x552+{int(self.screen_size[0] / 2 - 290)}+{int(self.screen_size[1] / 2 - 276)}"
        )
        self.previewWindow.resizable(False, False)

        self.canvas = tk.Canvas(self.previewWindow, width=400, height=540, bg="#f0f0f0")
        self.canvas.pack(side=tk.LEFT, padx=6, pady=6)

        self.ctrlFrame = tk.Frame(self.previewWindow, width=160, height=540)
        self.ctrlFrame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(0, 8), pady=8)

        self.cardNameLabel = tk.Label(
            self.ctrlFrame, text="", wraplength=150, justify=tk.CENTER, font=("", 10, "bold")
        )
        self.cardNameLabel.pack(pady=(4, 8))

        self.tipLabel = tk.Label(
            self.ctrlFrame,
            text="A/D or ←/→: Card\nW/S or ↑/↓: Print",
            fg="#555",
            justify=tk.CENTER,
        )
        self.tipLabel.pack(pady=(0, 10))

        self.cardRegionLabel = tk.Label(self.ctrlFrame, text="Region:")
        self.cardRegionLabel.pack(anchor=tk.W)

        self.cardRegionVar = tk.StringVar()
        self.cardRegionSelectorList: list[tk.Radiobutton] = []
        for region in self.regionEnum:
            rb = tk.Radiobutton(
                self.ctrlFrame,
                text=region,
                value=region,
                variable=self.cardRegionVar,
            )
            rb.pack(anchor=tk.W, padx=6)
            self.cardRegionSelectorList.append(rb)

        self.cardPrintLabel = tk.Label(self.ctrlFrame, text="Print / Alt Art:")
        self.cardPrintLabel.pack(anchor=tk.W, pady=(12, 2))

        self.cardPrintCombo = ttk.Combobox(self.ctrlFrame, width=14, state="readonly")
        self.cardPrintCombo.pack(fill=tk.X, pady=(0, 6))

        self.cardStatusLabel = tk.Label(self.ctrlFrame, text=" ", fg="#666")
        self.cardStatusLabel.pack(pady=4)

        self.cardsSplitBtn = tk.Button(
            self.ctrlFrame, text="Split 1 Copy", command=self.cards_split
        )
        self.cardsSplitBtn.pack(fill=tk.X, pady=(4, 12))

        self.navFrame = tk.Frame(self.ctrlFrame)
        self.navFrame.pack(fill=tk.X, pady=6)
        self.prevpicBtn = tk.Button(self.navFrame, text="← Prev", width=7, command=self.prevpic)
        self.nextpicBtn = tk.Button(self.navFrame, text="Next →", width=7, command=self.nextpic)
        self.prevpicBtn.pack(side=tk.LEFT)
        self.nextpicBtn.pack(side=tk.RIGHT)

        self.generateBtn = tk.Button(
            self.ctrlFrame,
            text="Generate A4 Layout",
            command=self.gen,
            height=2,
        )
        self.generateBtn.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 4))

        self.cRV_trace = self.cardRegionVar.trace_add("write", self.card_region_change)
        self.cardPrintCombo.bind("<<ComboboxSelected>>", self.print_change)
        self.previewWindow.bind("<KeyPress>", self.preview_kbd)

        self.refresh()

    def prevpic(self) -> None:
        if self.p > 0:
            self.p -= 1
            self.refresh()

    def nextpic(self) -> None:
        if self.p < self.picnum - 1:
            self.p += 1
            self.refresh()

    def cycle_print(self, direction: int) -> None:
        assert self.deck is not None
        card = self.deck.list[self.p]
        prints = card.get_prints()
        if len(prints) <= 1:
            return
        new_idx = (card.current + direction) % len(prints)
        self._switch_print_async(new_idx)

    def cards_split(self) -> None:
        assert self.deck is not None
        if self.deck.split_card(self.p):
            self.picnum = len(self.deck.list)
            self.p += 1
            self.refresh()

    def _switch_region_async(self, new_region: str) -> None:
        assert self.deck is not None
        card = self.deck.list[self.p]
        card.region = new_region
        card.current = 0
        card.expand_current()
        self.cardStatusLabel.config(text="Loading...")

        def worker():
            card.download()
            self.root.after(0, self.refresh)

        Thread(target=worker, daemon=True).start()

    def _switch_print_async(self, new_idx: int) -> None:
        assert self.deck is not None
        card = self.deck.list[self.p]
        card.current = new_idx
        card.expand_current()
        self.cardStatusLabel.config(text="Loading...")

        def worker():
            card.download()
            self.root.after(0, self.refresh)

        Thread(target=worker, daemon=True).start()

    def card_region_change(self, _varname, _index, _mode) -> None:
        self._switch_region_async(self.cardRegionVar.get())

    def print_change(self, event) -> None:
        val = event.widget.current()
        self._switch_print_async(val)

    def preview_kbd(self, event) -> None:
        keysym = event.keysym.lower()
        if keysym in ("a", "left"):
            self.prevpic()
        elif keysym in ("d", "right"):
            self.nextpic()
        elif keysym in ("w", "up"):
            self.cycle_print(-1)
        elif keysym in ("s", "down"):
            self.cycle_print(+1)

    def refresh(self) -> None:
        assert self.deck is not None
        if not self.previewWindow.winfo_exists():
            return

        card = self.deck.list[self.p]
        self.picnum = len(self.deck.list)

        self.cardRegionVar.trace_remove("write", self.cRV_trace)
        self.cardPrintCombo.unbind("<<ComboboxSelected>>")

        for i, region in enumerate(self.regionEnum):
            size = len(card.alts[region])
            self.cardRegionSelectorList[i].config(
                text=f"{region} ({size})",
                state="normal" if size > 0 else "disabled",
            )

        self.cardRegionVar.set(card.region)

        prints = card.get_prints()
        self.cardPrintCombo["value"] = prints
        if prints:
            self.cardPrintCombo.current(card.current)

        self.cardsSplitBtn.config(state="normal" if card.num > 1 else "disabled")
        self.cardNameLabel.config(text=f"{card.name}\n({card.pack} {card.id})  x{card.num}")
        self.cardStatusLabel.config(text="Auto-bleed active" if card.pic else "Image unavailable")
        self.previewWindow.title(
            f"Card Preview: {self.p + 1}/{self.picnum} (x{card.num})"
        )

        self.canvas.delete("all")
        if card.pic:
            composed = compose_card_with_bleed(card.pic, add_markers=True, crop_cut=False)
            preview = composed.resize((400, 540), resample=Image.Resampling.BICUBIC)
            self._preview_img = ImageTk.PhotoImage(preview)
            self.canvas.create_image(0, 0, anchor="nw", image=self._preview_img)
        else:
            self.canvas.create_text(200, 270, text="Failed to load image", fill="#c00")

        self.cRV_trace = self.cardRegionVar.trace_add("write", self.card_region_change)
        self.cardPrintCombo.bind("<<ComboboxSelected>>", self.print_change)

    def gen(self) -> None:
        assert self.deck is not None
        self.previewWindow.destroy()

        self.drawSubwindow = tk.Toplevel(self.root)
        disable_close_button(self.drawSubwindow)
        self.drawSubwindow.grab_set()
        self.drawSubwindow.geometry(
            f"320x48+{int(self.screen_size[0] / 2 - 160)}+{int(self.screen_size[1] / 2 - 24)}"
        )
        self.drawSubwindow.resizable(False, False)
        self.drawSubwindow.title("Generating...")
        self.drawBar = ttk.Progressbar(self.drawSubwindow, length=220)
        self.drawLabel = tk.Label(self.drawSubwindow, text=f"0/{self.deck.sum}")
        self.drawBar.pack(side=tk.LEFT, padx=10)
        self.drawLabel.pack(side=tk.RIGHT, padx=10)

        def on_progress(current: int, total: int) -> None:
            pct = current / total * 100 if total else 100
            self.root.after(0, self._update_draw_progress, current, total, pct)

        def on_done(out_dir: Path) -> None:
            self.root.after(0, self._on_draw_done, out_dir)

        def on_error(exc: Exception) -> None:
            self.root.after(0, self._on_draw_error, exc)

        def worker() -> None:
            try:
                draw(self.deck, on_progress, on_done)
            except Exception as exc:
                on_error(exc)

        Thread(target=worker, daemon=True).start()

    def _update_draw_progress(self, current: int, total: int, pct: float) -> None:
        if self.drawSubwindow.winfo_exists():
            self.drawBar["value"] = pct
            self.drawLabel.config(text=f"{current}/{total}")

    def _on_draw_done(self, out_dir: Path) -> None:
        if self.drawSubwindow.winfo_exists():
            self.drawLabel.config(text="Finished!")
            self.drawSubwindow.protocol("WM_DELETE_WINDOW", self.drawSubwindow.destroy)
        messagebox.showinfo("Finished", f"Layout images saved to:\n{out_dir}")

    def _on_draw_error(self, exc: Exception) -> None:
        if self.drawSubwindow.winfo_exists():
            self.drawSubwindow.destroy()
        messagebox.showerror("Generate Failed", f"Failed to generate layout:\n\n{exc}")


if __name__ == "__main__":
    GUI()
