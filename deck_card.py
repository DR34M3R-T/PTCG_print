from __future__ import annotations

import datetime
import os
import re
from io import BytesIO
from pathlib import Path
from typing import ClassVar

import pandas as pd
import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent
DB_DIR = REPO_ROOT / "database"
TEMP_DIR = REPO_ROOT / "temp"

REGIONS = ("en-US", "ja-JP", "zh-HK")

# ZH-HK promo codes mapped to equivalent JP promo codes for release-order sorting
ZH_PROMO_TO_JA = {
    "M-P": "MP",
    "SV-P": "SVP",
    "S-P": "SP",
    "SM-P": "SMP",
}

RE_LEADING_INT = re.compile(r"^(\d+)(.*)$")


def card_id_sort_key(card_id: str) -> tuple[int, tuple[tuple[int, int | str], ...]]:
    """Natural ascending sort key for card numbers (numeric-leading first)."""
    m = RE_LEADING_INT.match(card_id)
    group_rank = 0 if m else 1
    parts: list[tuple[int, int | str]] = []
    for tok in re.split(r"(\d+)", card_id):
        if not tok:
            continue
        if tok.isdigit():
            parts.append((0, int(tok)))
        else:
            parts.append((1, tok.lower()))
    return (group_rank, tuple(parts))


def _date_to_desc_int(date_str: str) -> int:
    """Convert YYYY-MM-DD to a descending integer key (newer date -> smaller key)."""
    s = date_str.strip() if isinstance(date_str, str) else ""
    if not s:
        return 0
    try:
        dt = datetime.date.fromisoformat(s)
        return -dt.toordinal()
    except ValueError:
        return 0

SECTION_PREFIXES = (
    "pokémon:",
    "pokemon:",
    "trainer:",
    "energy:",
    "total cards:",
    "spare:",
)

_HTTP_SESSION = requests.Session()
_HTTP_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }
)


def _is_valid_image_bytes(data: bytes) -> bool:
    if not data or len(data) < 256:
        return False
    try:
        with Image.open(BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False


class CardInfo:
    def __init__(
        self,
        region: str = "",
        pack: str = "",
        card_id: str = "",
        url: str = "",
        filename: str = "",
    ) -> None:
        self.region = region
        self.pack = pack
        self.id = card_id
        self.url = url
        self.filename = filename

    def getname(self) -> str:
        return f"{self.pack}_{self.id}"


class CardData:
    dtypes: ClassVar[dict[str, str]] = {"pack": "str", "id": "str", "group": "int", "url": "str"}
    database: ClassVar[dict[str, pd.DataFrame] | None] = None
    sets_meta: ClassVar[dict[str, dict[str, dict[str, object]]] | None] = None
    en_url_pref: ClassVar[str] = "https://limitlesstcg.nyc3.digitaloceanspaces.com/tpci/"
    ja_url_pref: ClassVar[str] = "https://limitlesstcg.nyc3.digitaloceanspaces.com/tpc/"
    zh_url_pref: ClassVar[str] = "https://asia.pokemon-card.com/hk/card-img"

    @classmethod
    def get_database(cls, reload: bool = False) -> dict[str, pd.DataFrame]:
        if cls.database is None or reload:
            cls.database = {
                "en-US": pd.read_csv(DB_DIR / "en_data.csv", dtype=cls.dtypes),
                "ja-JP": pd.read_csv(DB_DIR / "ja_data.csv", dtype=cls.dtypes),
                "zh-HK": pd.read_csv(DB_DIR / "zh_data.csv", dtype=cls.dtypes),
            }
        return cls.database

    @classmethod
    def get_sets_meta(cls, reload: bool = False) -> dict[str, dict[str, dict[str, object]]]:
        if cls.sets_meta is None or reload:
            meta: dict[str, dict[str, dict[str, object]]] = {r: {} for r in REGIONS}
            sets_path = DB_DIR / "sets.csv"
            if sets_path.exists():
                df = pd.read_csv(sets_path, dtype=str).fillna("")
                for _, row in df.iterrows():
                    region = row.get("region", "").strip()
                    code = row.get("code", "").strip()
                    if not region or not code:
                        continue
                    order_raw = row.get("order", "").strip()
                    order_val = int(order_raw) if order_raw.isdigit() else None
                    meta.setdefault(region, {})[code] = {
                        "name": row.get("name", "").strip(),
                        "era": row.get("era", "").strip(),
                        "release_date": row.get("release_date", "").strip(),
                        "card_count": int(row["card_count"]) if row.get("card_count", "").strip().isdigit() else 0,
                        "order": order_val,
                    }
            cls.sets_meta = meta
        return cls.sets_meta

    @classmethod
    def _set_sort_key(cls, region: str, pack: str) -> tuple[int, int, str]:
        """Primary sort key for a print's set: newest -> oldest, Promo before era sets."""
        sets_meta = cls.get_sets_meta()
        info = sets_meta.get(region, {}).get(pack)
        if info is None and region == "zh-HK":
            ja_pack = ZH_PROMO_TO_JA.get(pack, pack)
            info = sets_meta.get("ja-JP", {}).get(ja_pack)

        if info is not None:
            order_val = info.get("order")
            if isinstance(order_val, int):
                return (0, order_val, pack)
            rel_date = str(info.get("release_date", ""))
            if rel_date:
                return (1, _date_to_desc_int(rel_date), pack)
            return (2, 0, pack)
        return (3, 0, pack)

    @classmethod
    def _print_sort_key(cls, card_info: CardInfo) -> tuple[tuple[int, int, str], tuple[int, tuple[tuple[int, int | str], ...]]]:
        return (cls._set_sort_key(card_info.region, card_info.pack), card_id_sort_key(card_info.id))

    @staticmethod
    def _cache_filename_from_url(region: str, pack: str, card_id: str, url: str) -> str:
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", card_id)
        if "limitlesstcg" in url:
            base = url.rstrip("/").split("/")[-1]
            if base:
                return base
        ext = ".png"
        tail = url.split("?")[0].rstrip("/").split("/")[-1]
        if "." in tail:
            ext = "." + tail.rsplit(".", 1)[-1]
        tag = "EN" if region == "en-US" else "JP"
        return f"{pack}_{safe_id}_R_{tag}{ext}"

    @classmethod
    def _build_en_info(cls, pack: str, card_id: str, url: str | None = None) -> CardInfo:
        clean_url = url.strip() if isinstance(url, str) and url.strip() else ""
        if clean_url:
            filename = cls._cache_filename_from_url("en-US", pack, card_id, clean_url)
            return CardInfo("en-US", pack, card_id, clean_url, filename)
        str_id = card_id.rjust(3, "0") if card_id.isdigit() else card_id
        filename = f"{pack}_{str_id}_R_EN.png"
        fallback_url = f"{cls.en_url_pref}{pack}/{filename}"
        return CardInfo("en-US", pack, card_id, fallback_url, filename)

    @classmethod
    def _build_ja_info(cls, pack: str, card_id: str, url: str | None = None) -> CardInfo:
        clean_url = url.strip() if isinstance(url, str) and url.strip() else ""
        if clean_url:
            filename = cls._cache_filename_from_url("ja-JP", pack, card_id, clean_url)
            return CardInfo("ja-JP", pack, card_id, clean_url, filename)
        filename = f"{pack}_{card_id}_R_JP.png"
        fallback_url = f"{cls.ja_url_pref}{pack}/{filename}"
        return CardInfo("ja-JP", pack, card_id, fallback_url, filename)

    @classmethod
    def _build_zh_info(cls, pack: str, card_id: str, filename: str) -> CardInfo:
        url = f"{cls.zh_url_pref}/{filename}"
        return CardInfo("zh-HK", pack, card_id, url, filename)

    @classmethod
    def _query_card(cls, region: str, pack: str, card_id: str) -> pd.DataFrame:
        df = cls.get_database()[region]
        hit = df[(df["pack"] == pack) & (df["id"] == card_id)]
        if len(hit) == 0 and card_id.isdigit():
            norm_id = card_id.lstrip("0") or "0"
            if norm_id != card_id:
                hit = df[(df["pack"] == pack) & (df["id"] == norm_id)]
        return hit

    def __init__(self, raw: str = "", preferred_region: str = "en-US") -> None:
        self.num: int = 0
        self.name: str = ""
        self.group: int = -1
        self.region: str = preferred_region
        self.preferred_region: str = preferred_region
        self.base_region: str = ""
        self.base_pack: str = ""
        self.base_id: str = ""
        self.pack: str = ""
        self.id: str = ""
        self.url: str = ""
        self.filename: str = ""
        self.pic: bytes | None = None
        self.last_error: str = ""
        self.pic_with_frame: Image.Image | None = None
        self.alts: dict[str, list[CardInfo]] = {r: [] for r in REGIONS}
        self.current: int = 0
        self.raw: str = raw.strip()
        if raw:
            self.parse(raw)

    def parse(self, raw: str) -> int:
        line = raw.strip()
        if not line or line.startswith("#"):
            return 0
        if line.lower().startswith(SECTION_PREFIXES):
            return 0

        words = line.split()
        if len(words) < 4 or not words[0].isdigit():
            return -1

        try:
            count = int(words[0])
            if count <= 0:
                return -1
            if words[-1] == "PH":
                words.pop()
                if len(words) < 4:
                    return -1

            pack = words[-2]
            raw_id = words[-1]
            card_name = " ".join(words[1:-2])

            hit = self._query_card("en-US", pack, raw_id)
            if len(hit) > 0:
                matched_id = str(hit["id"].values[0])
                matched_url = hit["url"].values[0] if "url" in hit.columns else ""
                info = self._build_en_info(pack, matched_id, matched_url)
            else:
                # Fallback for JP-only / not-yet-released EN sets
                hit = self._query_card("ja-JP", pack, raw_id)
                if len(hit) == 0:
                    return -1
                matched_id = str(hit["id"].values[0])
                matched_url = hit["url"].values[0] if "url" in hit.columns else ""
                info = self._build_ja_info(pack, matched_id, matched_url)

            self.num = count
            self.name = card_name
            self.region = info.region
            self.base_region = info.region
            self.base_pack = info.pack
            self.base_id = info.id
            self.group = int(hit["group"].values[0])
            return 1
        except Exception:
            return -1

    def get_alts(self) -> None:
        if self.group <= 0:
            return
        db = self.get_database()
        self.alts = {r: [] for r in REGIONS}

        seen_keys: dict[str, set[tuple[str, str]]] = {r: set() for r in REGIONS}

        # CSVs are pre-sorted by release date (newest -> oldest, Promo before era sets) then card id ascending
        en_ingroup = db["en-US"][db["en-US"]["group"] == self.group]
        for _, row in en_ingroup.iterrows():
            key = (str(row["pack"]), str(row["id"]))
            if key in seen_keys["en-US"]:
                continue
            seen_keys["en-US"].add(key)
            row_url = row["url"] if "url" in row and pd.notna(row["url"]) else ""
            self.alts["en-US"].append(self._build_en_info(key[0], key[1], row_url))

        ja_ingroup = db["ja-JP"][db["ja-JP"]["group"] == self.group]
        for _, row in ja_ingroup.iterrows():
            key = (str(row["pack"]), str(row["id"]))
            if key in seen_keys["ja-JP"]:
                continue
            seen_keys["ja-JP"].add(key)
            row_url = row["url"] if "url" in row and pd.notna(row["url"]) else ""
            self.alts["ja-JP"].append(self._build_ja_info(key[0], key[1], row_url))

        zh_ingroup = db["zh-HK"][db["zh-HK"]["group"] == self.group]
        for _, row in zh_ingroup.iterrows():
            key = (str(row["pack"]), str(row["id"]))
            if key in seen_keys["zh-HK"]:
                continue
            seen_keys["zh-HK"].add(key)
            self.alts["zh-HK"].append(
                self._build_zh_info(key[0], key[1], str(row["filename"]))
            )

        # Always sort prints in business logic using sets.csv (newest -> oldest, Promo before era) + card id asc
        for r in REGIONS:
            self.alts[r].sort(key=self._print_sort_key)

        # Honor user's preferred region if available; otherwise keep base_region
        if self.preferred_region in self.alts and len(self.alts[self.preferred_region]) > 0:
            self.region = self.preferred_region
        elif self.base_region in self.alts and len(self.alts[self.base_region]) > 0:
            self.region = self.base_region

        # Default to the deck-specified print when staying in base_region; newest (0) when switching regions
        self.current = 0
        if self.region == self.base_region:
            for idx, item in enumerate(self.alts[self.region]):
                if item.pack == self.base_pack and item.id == self.base_id:
                    self.current = idx
                    break

    def expand_current(self) -> None:
        prints = self.alts.get(self.region, [])
        if not prints:
            for fallback in REGIONS:
                if self.alts[fallback]:
                    self.region = fallback
                    prints = self.alts[fallback]
                    self.current = 0
                    break
        if not prints:
            raise ValueError(f"No available prints for card {self.name} (group={self.group})")

        if self.current >= len(prints) or self.current < 0:
            self.current = 0

        chosen = prints[self.current]
        self.region = chosen.region
        self.pack = chosen.pack
        self.id = chosen.id
        self.url = chosen.url
        self.filename = chosen.filename

    def get_prints(self) -> list[str]:
        return [card.getname() for card in self.alts[self.region]]

    def clone_single(self) -> CardData:
        """Create a 1-copy clone sharing alt lists so user can pick a different art."""
        copy_card = CardData(preferred_region=self.preferred_region)
        copy_card.num = 1
        copy_card.name = self.name
        copy_card.group = self.group
        copy_card.region = self.region
        copy_card.alts = {r: list(items) for r, items in self.alts.items()}
        copy_card.current = self.current
        copy_card.expand_current()
        copy_card.pic = self.pic
        return copy_card

    def download(self, retries: int = 3) -> int:
        self.last_error = ""
        cache_path = TEMP_DIR / self.filename

        if cache_path.exists():
            try:
                data = cache_path.read_bytes()
                if _is_valid_image_bytes(data):
                    self.pic = data
                    return 1
                cache_path.unlink()
            except OSError:
                pass

        for _ in range(retries):
            try:
                resp = _HTTP_SESSION.get(self.url, timeout=(10, 30))
                if resp.status_code == 200 and _is_valid_image_bytes(resp.content):
                    self.pic = resp.content
                    try:
                        TEMP_DIR.mkdir(parents=True, exist_ok=True)
                        tmp_path = cache_path.with_suffix(".tmp")
                        tmp_path.write_bytes(self.pic)
                        os.replace(tmp_path, cache_path)
                    except OSError as cache_err:
                        # Cache write failure should not discard the already downloaded image
                        self.last_error = f"cache write skipped: {cache_err}"
                    return 1
                self.last_error = f"HTTP {resp.status_code}"
                if resp.status_code == 404:
                    break
            except Exception as exc:
                self.last_error = str(exc)
                continue

        return -1


class DeckData:
    def __init__(self, deck: str, region: str = "en-US") -> None:
        self.sum: int = 0
        self.list: list[CardData] = []
        self.unmatched_lines: list[str] = []
        now = datetime.datetime.now()
        self.region = region
        self.name = now.strftime("%y-%m-%d_%H-%M-%S")
        self.loadtime = self.name
        self.__load(deck)

    def __load(self, deck: str) -> None:
        lines = deck.replace("\r\n", "\n").split("\n")
        if lines and lines[0].startswith("Deckname:"):
            raw_name = lines.pop(0)[len("Deckname:") :].strip()
            if raw_name:
                if not re.fullmatch(r"[-\u4e00-\u9fa5_\w\s]{1,50}", raw_name):
                    raise ValueError(f"Invalid Deckname: {raw_name!r}")
                self.name = raw_name

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith(SECTION_PREFIXES):
                continue

            card = CardData(raw=stripped, preferred_region=self.region)
            if card.num > 0:
                self.sum += card.num
                self.list.append(card)
            else:
                self.unmatched_lines.append(stripped)

        if not self.list:
            raise ValueError("No valid cards found in deck list.")

    def split_card(self, index: int) -> bool:
        """Split 1 copy off card at `index` into a new entry right after it."""
        if index < 0 or index >= len(self.list):
            return False
        target = self.list[index]
        if target.num <= 1:
            return False
        target.num -= 1
        cloned = target.clone_single()
        self.list.insert(index + 1, cloned)
        return True
