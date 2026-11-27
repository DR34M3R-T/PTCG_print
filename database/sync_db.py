# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests>=2.32",
#   "beautifulsoup4>=4.12",
#   "lxml>=5.0",
#   "pillow>=10.0",
# ]
# ///
"""
Incremental PTCG card database builder & synchronizer.

Pipeline:
1. Incrementally fetch EN & JP set lists and card print tables from Limitless TCG
   into `database/limitless_cache.json` (only new or changed sets are fetched).
2. Run a global Union-Find across all EN + JP prints so identical cards across
   all reprints and languages share a single collision-free, deterministic group_id.
3. Incrementally scan local ZH-HK card images (e.g. E:/PTCG_zh-Hant), detect
   high-resolution PNGs (>= 736x1024 by default), fetch detail metadata from
   asia.pokemon-card.com/hk only for newly discovered hi-res files, and append
   to `database/zh_hidpi_cache.csv`.
4. Map ZH-HK cards to JP group_ids in tiers:
   - Tier 0: explicit overrides from `database/zh_manual_map.json`
   - Tier 1: Basic Energy cards (GRA/FIR/WAT/LIG/PSY/FIG/DAR/MET/FAI)
   - Tier 2: regular expansions / matching sets by (pack, normalized_id)
   - Tier 3: unmatched promos & exclusive decks exported to `database/zh_unmatched.csv`
5. Write clean CSVs without `bleed_id`:
   - `database/en_data.csv` (pack,id,name,group)
   - `database/ja_data.csv` (pack,id,name,group)
   - `database/zh_data.csv` (pack,id,filename,group)
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "database"

LIMITLESS_CACHE_PATH = DB_DIR / "limitless_cache.json"
ZH_HIDPI_CACHE_PATH = DB_DIR / "zh_hidpi_cache.csv"
ZH_SCAN_STATE_PATH = DB_DIR / "zh_scan_state.json"
ZH_MANUAL_MAP_PATH = DB_DIR / "zh_manual_map.json"
ZH_UNMATCHED_PATH = DB_DIR / "zh_unmatched.csv"

EN_CSV_PATH = DB_DIR / "en_data.csv"
JA_CSV_PATH = DB_DIR / "ja_data.csv"
ZH_CSV_PATH = DB_DIR / "zh_data.csv"
SETS_CSV_PATH = DB_DIR / "sets.csv"

DEFAULT_ZH_IMG_DIR = Path(r"E:\PTCG_zh-Hant")
DEFAULT_ZH_SEED_CSV = REPO_ROOT.parent / "PTCG_cardump" / "zh_hidpi.csv"

EN_SET_LIST_URL = "https://limitlesstcg.com/cards"
JA_SET_LIST_URL = "https://limitlesstcg.com/cards/jp"
EN_SET_FULL_URL = "https://limitlesstcg.com/cards/{pack}?display=full"
JA_SET_FULL_URL = "https://limitlesstcg.com/cards/jp/{pack}?display=full"
ZH_DETAIL_URL = "https://asia.pokemon-card.com/hk/card-search/detail/{card_id}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
}

NON_EN_CARD_SEGMENTS = {
    "jp",
    "de",
    "fr",
    "it",
    "es",
    "es-la",
    "pt",
    "en",
    "advanced",
    "syntax",
    "pokedex",
    "translations",
}

RE_JP_CARD_HREF = re.compile(r"^/cards/jp/([^/?#]+)/([^/?#]+)$")
RE_EN_CARD_HREF = re.compile(r"^/cards/(?:en/)?([^/?#]+)/([^/?#]+)$")
RE_HK_FILENAME = re.compile(r"^hk(\d+)\.png$", re.IGNORECASE)
RE_LEADING_INT = re.compile(r"^(\d+)(.*)$")

# Basic energy code -> list of anchor cards (lang, pack, id) to resolve its group_id
ENERGY_ANCHORS: dict[str, list[tuple[str, str, str]]] = {
    "GRA": [("ja", "MC", "G"), ("en", "SVE", "1"), ("en", "MEE", "1"), ("en", "BS", "99")],
    "FIR": [("ja", "MC", "R"), ("en", "SVE", "2"), ("en", "MEE", "2"), ("en", "BS", "98")],
    "WAT": [("ja", "MC", "W"), ("en", "SVE", "3"), ("en", "MEE", "3"), ("en", "BS", "102")],
    "LIG": [("ja", "MC", "L"), ("en", "SVE", "4"), ("en", "MEE", "4"), ("en", "BS", "100")],
    "PSY": [("ja", "MC", "P"), ("en", "SVE", "5"), ("en", "MEE", "5"), ("en", "BS", "101")],
    "FIG": [("ja", "MC", "F"), ("en", "SVE", "6"), ("en", "MEE", "6"), ("en", "BS", "97")],
    "DAR": [("ja", "MC", "D"), ("en", "SVE", "7"), ("en", "MEE", "7")],
    "MET": [("ja", "MC", "M"), ("en", "SVE", "8"), ("en", "MEE", "8")],
    "FAI": [("ja", "SM12a", "Y"), ("en", "XY", "140"), ("en", "SUM", "172"), ("en", "GEN", "83")],
}

ZH_PROMO_PACKS = {"S-P", "SV-P", "M-P", "SM-P"}

_thread_local = threading.local()


def get_session(proxy: str | None = None) -> requests.Session:
    session: requests.Session | None = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
        _thread_local.session = session
    return session


def fetch_with_retry(
    url: str,
    proxy: str | None = None,
    timeout: tuple[int, int] = (15, 60),
    retries: int = 5,
) -> requests.Response:
    last_err: Exception | None = None
    session = get_session(proxy)
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (404, 410):
                return resp
            last_err = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as exc:
            last_err = exc
        sleep_s = min(2.0 * attempt, 10.0)
        time.sleep(sleep_s)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_err}")


def atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def atomic_write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Step 1: Limitless TCG incremental scraping
# ---------------------------------------------------------------------------

def normalize_release_date(raw_date: str) -> str:
    raw = raw_date.strip()
    if not raw:
        return ""
    for fmt in ("%d %b %y", "%Y-%m-%d", "%d %b %Y"):
        try:
            dt = datetime.datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def parse_set_list(url: str, lang: str, proxy: str | None = None) -> list[dict[str, Any]]:
    resp = fetch_with_retry(url, proxy=proxy)
    if resp.status_code != 200:
        raise RuntimeError(f"Cannot load set list {url}: HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.content, "lxml")
    table = soup.find("table", class_="sets-table")
    if not table:
        raise RuntimeError(f"sets-table not found on {url}")

    sets: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_era = ""
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        tds = tr.find_all("td")
        if len(ths) == 1 and not tds:
            current_era = ths[0].get_text(" ", strip=True)
            continue
        if len(tds) < 3:
            continue
        link = tds[0].find("a")
        if not link or not link.get("href"):
            continue
        href = link["href"].strip().rstrip("/")
        code = href.split("/")[-1]
        if not code or code in seen:
            continue
        seen.add(code)

        code_span = link.find("span")
        full_text = link.get_text(" ", strip=True)
        if code_span:
            span_txt = code_span.get_text(strip=True)
            name = full_text[: -len(span_txt)].strip() if full_text.endswith(span_txt) else full_text
        else:
            name = full_text

        release_date = normalize_release_date(tds[1].get_text(strip=True))
        count_tokens = tds[2].get_text(" ", strip=True).split()
        card_count = int(count_tokens[0]) if count_tokens and count_tokens[0].isdigit() else 0

        sets.append(
            {
                "code": code,
                "name": name,
                "era": current_era,
                "release_date": release_date,
                "card_count": card_count,
            }
        )

    # Limitless lists newest first; reverse to oldest -> newest for stable indexing
    sets.reverse()
    return sets


def parse_print_href(href: str) -> tuple[str, str, str] | None:
    href = href.split("?")[0].split("#")[0].rstrip("/")
    m_jp = RE_JP_CARD_HREF.match(href)
    if m_jp:
        return ("ja", m_jp.group(1), m_jp.group(2))
    m_en = RE_EN_CARD_HREF.match(href)
    if m_en and m_en.group(1).lower() not in NON_EN_CARD_SEGMENTS:
        return ("en", m_en.group(1), m_en.group(2))
    return None


def normalize_card_image_url(src: str | None) -> str:
    if not src:
        return ""
    src = src.strip()
    # Limitless CDN serves 460x640 at *_LG.png and full 736x1024 without _LG
    if "limitlesstcg" in src and src.endswith("_LG.png"):
        return src[: -len("_LG.png")] + ".png"
    return src


def parse_set_full_page(
    lang: str,
    pack_code: str,
    proxy: str | None = None,
) -> list[dict[str, Any]]:
    url = (EN_SET_FULL_URL if lang == "en" else JA_SET_FULL_URL).format(pack=pack_code)
    resp = fetch_with_retry(url, proxy=proxy, timeout=(15, 90))
    if resp.status_code != 200:
        raise RuntimeError(f"Failed fetching {lang}:{pack_code} ({url}): HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.content, "lxml")
    cards_html = soup.find_all("div", class_="card-page-main")
    parsed_cards: list[dict[str, Any]] = []

    for card_html in cards_html:
        name_el = card_html.find("span", class_="card-text-name")
        card_name = name_el.get_text(strip=True) if name_el else ""

        img_el = card_html.find("img", class_="card")
        img_url = normalize_card_image_url(img_el.get("src") if img_el else None)

        card_num = ""
        # Prefer extracting exact id from the card title link href
        name_link = name_el.find("a") if name_el else None
        if not name_link and name_el and name_el.parent and name_el.parent.name == "a":
            name_link = name_el.parent
        if name_link and name_link.get("href"):
            parsed = parse_print_href(name_link["href"])
            if parsed and parsed[1] == pack_code:
                card_num = parsed[2]

        # Fallback: prints-current-details span containing "#<num>"
        if not card_num:
            det = card_html.find("div", class_="prints-current-details")
            if det:
                spans = det.find_all("span")
                for sp in spans[1:]:
                    txt = sp.get_text(" ", strip=True)
                    m = re.search(r"#(\S+)", txt)
                    if m:
                        card_num = m.group(1)
                        break

        if not card_num:
            continue

        en_prints: set[tuple[str, str]] = set()
        ja_prints: set[tuple[str, str]] = set()
        if lang == "en":
            en_prints.add((pack_code, card_num))
        else:
            ja_prints.add((pack_code, card_num))

        tb = card_html.find("table", class_="card-prints-versions")
        if tb:
            # Parse ALL links in the table (including rows hidden behind "Show all prints")
            for a in tb.find_all("a", href=True):
                parsed = parse_print_href(a["href"])
                if not parsed:
                    continue
                p_lang, p_pack, p_id = parsed
                if p_lang == "en":
                    en_prints.add((p_pack, p_id))
                else:
                    ja_prints.add((p_pack, p_id))

        parsed_cards.append(
            {
                "id": card_num,
                "name": card_name,
                "url": img_url,
                "en_prints": sorted([list(x) for x in en_prints]),
                "ja_prints": sorted([list(x) for x in ja_prints]),
            }
        )

    return parsed_cards


def load_limitless_cache() -> dict[str, Any]:
    if LIMITLESS_CACHE_PATH.exists():
        with LIMITLESS_CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"en_sets": [], "ja_sets": [], "en": {}, "ja": {}}


def sync_limitless(
    cache: dict[str, Any],
    workers: int = 6,
    force_all: bool = False,
    force_sets: set[str] | None = None,
    proxy: str | None = None,
) -> dict[str, Any]:
    force_sets = force_sets or set()
    print("[1/4] Fetching EN & JP set lists from Limitless TCG...", flush=True)
    en_sets = parse_set_list(EN_SET_LIST_URL, "en", proxy=proxy)
    ja_sets = parse_set_list(JA_SET_LIST_URL, "ja", proxy=proxy)
    cache["en_sets"] = en_sets
    cache["ja_sets"] = ja_sets
    print(f"      Found {len(en_sets)} EN sets, {len(ja_sets)} JP sets.", flush=True)

    tasks: list[tuple[str, dict[str, Any]]] = []
    for lang, sets_meta in (("en", en_sets), ("ja", ja_sets)):
        bucket = cache.setdefault(lang, {})
        for s in sets_meta:
            code = s["code"]
            expected = s["card_count"]
            cached = bucket.get(code)
            cached_cards = cached.get("cards", []) if cached else []
            missing_url = bool(cached_cards) and "url" not in cached_cards[0]
            need_fetch = (
                force_all
                or code in force_sets
                or f"{lang}:{code}" in force_sets
                or cached is None
                or expected == 0
                or cached.get("card_count") != expected
                or len(cached_cards) == 0
                or missing_url
            )
            if need_fetch:
                tasks.append((lang, s))

    print(f"      Sets to fetch: {len(tasks)} (cached skipped: {len(en_sets) + len(ja_sets) - len(tasks)})", flush=True)
    if not tasks:
        atomic_write_json(LIMITLESS_CACHE_PATH, cache)
        return cache

    completed = 0
    failed: list[str] = []
    lock = threading.Lock()

    def worker(item: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        lang, meta = item
        cards = parse_set_full_page(lang, meta["code"], proxy=proxy)
        return lang, meta, cards

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(worker, t): t for t in tasks}
        for fut in as_completed(futures):
            lang, meta = futures[fut]
            code = meta["code"]
            try:
                _, _, cards = fut.result()
                with lock:
                    cache[lang][code] = {
                        "card_count": meta["card_count"],
                        "cards": cards,
                    }
                    completed += 1
                    print(
                        f"      [{completed}/{len(tasks)}] {lang.upper()}:{code} -> {len(cards)} cards",
                        flush=True,
                    )
                    if completed % 15 == 0:
                        atomic_write_json(LIMITLESS_CACHE_PATH, cache)
            except Exception as exc:
                with lock:
                    failed.append(f"{lang}:{code} ({exc})")
                    print(f"      [ERR] {lang.upper()}:{code}: {exc}", flush=True)

    atomic_write_json(LIMITLESS_CACHE_PATH, cache)
    if failed:
        print(f"      WARNING: {len(failed)} sets failed: {failed[:10]}", flush=True)
    return cache


# ---------------------------------------------------------------------------
# Step 2: Global Union-Find grouping across EN + JP
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str, str], tuple[str, str, str]] = {}

    def find(self, x: tuple[str, str, str]) -> tuple[str, str, str]:
        if x not in self.parent:
            self.parent[x] = x
            return x
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a: tuple[str, str, str], b: tuple[str, str, str]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def build_en_ja_groups(
    cache: dict[str, Any],
) -> tuple[
    list[list[Any]],
    list[list[Any]],
    dict[tuple[str, str, str], int],
]:
    print("[2/4] Running global Union-Find grouping across EN + JP...", flush=True)
    uf = UnionFind()

    # Collect ordered canonical cards (oldest set -> newest set)
    en_cards_ordered: list[tuple[str, str, str, str]] = []  # (pack, id, name, url)
    ja_cards_ordered: list[tuple[str, str, str, str]] = []

    seen_en: set[tuple[str, str]] = set()
    for s in cache.get("en_sets", []):
        code = s["code"]
        entry = cache.get("en", {}).get(code)
        if not entry:
            continue
        for c in entry.get("cards", []):
            cid = str(c["id"])
            if (code, cid) in seen_en:
                continue
            seen_en.add((code, cid))
            node = ("en", code, cid)
            uf.find(node)
            for p_pack, p_id in c.get("en_prints", []):
                uf.union(node, ("en", str(p_pack), str(p_id)))
            for p_pack, p_id in c.get("ja_prints", []):
                uf.union(node, ("ja", str(p_pack), str(p_id)))
            en_cards_ordered.append((code, cid, c.get("name", ""), c.get("url", "")))

    seen_ja: set[tuple[str, str]] = set()
    for s in cache.get("ja_sets", []):
        code = s["code"]
        entry = cache.get("ja", {}).get(code)
        if not entry:
            continue
        for c in entry.get("cards", []):
            cid = str(c["id"])
            if (code, cid) in seen_ja:
                continue
            seen_ja.add((code, cid))
            node = ("ja", code, cid)
            uf.find(node)
            for p_pack, p_id in c.get("en_prints", []):
                uf.union(node, ("en", str(p_pack), str(p_id)))
            for p_pack, p_id in c.get("ja_prints", []):
                uf.union(node, ("ja", str(p_pack), str(p_id)))
            ja_cards_ordered.append((code, cid, c.get("name", ""), c.get("url", "")))

    # Deterministic group_id assignment in oldest-first canonical order
    root_to_gid: dict[tuple[str, str, str], int] = {}
    next_gid = 1

    def get_gid(node: tuple[str, str, str]) -> int:
        nonlocal next_gid
        r = uf.find(node)
        gid = root_to_gid.get(r)
        if gid is None:
            gid = next_gid
            next_gid += 1
            root_to_gid[r] = gid
        return gid

    node_to_gid: dict[tuple[str, str, str], int] = {}
    en_rows: list[list[Any]] = []
    skipped_en_non_cdn = 0
    for pack, cid, name, url in en_cards_ordered:
        node = ("en", pack, cid)
        gid = get_gid(node)
        node_to_gid[node] = gid
        if "limitlesstcg" not in url:
            skipped_en_non_cdn += 1
            continue
        en_rows.append([pack, cid, name, gid, url])

    ja_rows: list[list[Any]] = []
    skipped_ja_non_cdn = 0
    for pack, cid, name, url in ja_cards_ordered:
        node = ("ja", pack, cid)
        gid = get_gid(node)
        node_to_gid[node] = gid
        if "limitlesstcg" not in url:
            skipped_ja_non_cdn += 1
            continue
        ja_rows.append([pack, cid, name, gid, url])

    en_set_order = {s["code"]: idx for idx, s in enumerate(cache.get("en_sets", []))}
    ja_set_order = {s["code"]: idx for idx, s in enumerate(cache.get("ja_sets", []))}

    en_rows.sort(key=lambda r: (-en_set_order.get(r[0], -1), card_id_sort_key(r[1])))
    ja_rows.sort(key=lambda r: (-ja_set_order.get(r[0], -1), card_id_sort_key(r[1])))

    en_gids = {r[3] for r in en_rows}
    ja_gids = {r[3] for r in ja_rows}
    shared = len(en_gids & ja_gids)
    print(
        f"      EN cards: {len(en_rows)} ({len(en_gids)} groups, skipped non-CDN={skipped_en_non_cdn}) | "
        f"JP cards: {len(ja_rows)} ({len(ja_gids)} groups, skipped non-CDN={skipped_ja_non_cdn}) | "
        f"Shared EN<->JP groups: {shared}",
        flush=True,
    )
    return en_rows, ja_rows, node_to_gid


# ---------------------------------------------------------------------------
# Step 3: ZH-HK incremental hi-res image scanner & detail fetcher
# ---------------------------------------------------------------------------

def seed_zh_cache_if_needed(seed_csv: Path) -> None:
    if ZH_HIDPI_CACHE_PATH.exists():
        return
    if not seed_csv.exists():
        atomic_write_csv(
            ZH_HIDPI_CACHE_PATH,
            ["filename", "pack", "id", "width", "height", "name", "illustrator"],
            [],
        )
        atomic_write_json(ZH_SCAN_STATE_PATH, {"last_scanned_num": 0})
        return

    print(f"      Seeding {ZH_HIDPI_CACHE_PATH.name} from {seed_csv}...", flush=True)
    rows: list[list[str]] = []
    max_num = 0
    with seed_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for idx, row in enumerate(reader):
            if not row:
                continue
            if idx == 0 and row[0].strip().lower() == "filename":
                continue
            if len(row) < 3:
                continue
            fname, pack, cid = row[0].strip(), row[1].strip(), row[2].strip()
            m = RE_HK_FILENAME.match(fname)
            if m:
                max_num = max(max_num, int(m.group(1)))
            if pack == "None" or cid == "None":
                continue
            rows.append([fname, pack, cid, "", "", "", ""])

    atomic_write_csv(
        ZH_HIDPI_CACHE_PATH,
        ["filename", "pack", "id", "width", "height", "name", "illustrator"],
        rows,
    )
    atomic_write_json(ZH_SCAN_STATE_PATH, {"last_scanned_num": max_num})
    print(f"      Seeded {len(rows)} ZH hi-res records (up to hk{max_num:08d}.png).", flush=True)


def load_zh_cache() -> tuple[list[dict[str, str]], dict[str, int]]:
    records: list[dict[str, str]] = []
    if ZH_HIDPI_CACHE_PATH.exists():
        with ZH_HIDPI_CACHE_PATH.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))
    state = {"last_scanned_num": 0}
    if ZH_SCAN_STATE_PATH.exists():
        with ZH_SCAN_STATE_PATH.open("r", encoding="utf-8") as f:
            state = json.load(f)
    return records, state


def save_zh_cache(records: list[dict[str, str]], state: dict[str, int]) -> None:
    cols = ["filename", "pack", "id", "width", "height", "name", "illustrator"]
    rows = [[r.get(c, "") for c in cols] for r in records]
    atomic_write_csv(ZH_HIDPI_CACHE_PATH, cols, rows)
    atomic_write_json(ZH_SCAN_STATE_PATH, state)


def fetch_zh_card_detail(file_num: int, proxy: str | None = None) -> dict[str, str] | None:
    url = ZH_DETAIL_URL.format(card_id=file_num)
    resp = fetch_with_retry(url, proxy=proxy, timeout=(15, 30), retries=4)
    if resp.status_code != 200 or resp.url.rstrip("/") != url.rstrip("/"):
        return None

    soup = BeautifulSoup(resp.content, "lxml")
    exp_col = soup.find(class_="expansionLinkColumn")
    pack = ""
    if exp_col:
        a = exp_col.find("a", href=True)
        if a and "=" in a["href"]:
            pack = a["href"].split("=")[-1].strip()
    if not pack:
        return None

    cid_el = soup.find(class_="collectorNumber")
    cid = cid_el.get_text(strip=True) if cid_el else ""
    if "/" in cid:
        cid = cid.split("/")[0].strip()
    if not cid:
        return None

    h1 = soup.find("h1")
    name = ""
    if h1:
        # Remove stage span text like "基礎" / "1階進化" if present
        h1_clone = BeautifulSoup(str(h1), "lxml").find("h1")
        for sp in h1_clone.find_all("span"):
            sp.decompose()
        name = h1_clone.get_text(" ", strip=True)

    illus_el = soup.find("a", href=re.compile(r"illustratorName="))
    illustrator = illus_el.get_text(strip=True) if illus_el else ""

    return {
        "pack": pack,
        "id": cid,
        "name": name,
        "illustrator": illustrator,
    }


def scan_zh_incremental(
    zh_img_dir: Path,
    seed_csv: Path,
    min_width: int = 736,
    min_height: int = 1024,
    workers: int = 4,
    rescan_all: bool = False,
    proxy: str | None = None,
) -> list[dict[str, str]]:
    print("[3/4] Scanning local ZH-HK images & fetching new hi-res metadata...", flush=True)
    seed_zh_cache_if_needed(seed_csv)
    records, state = load_zh_cache()
    known_files = {r["filename"] for r in records}
    last_scanned = 0 if rescan_all else int(state.get("last_scanned_num", 0))

    if not zh_img_dir.exists():
        print(f"      ZH image dir not found ({zh_img_dir}); using existing {len(records)} cached records.", flush=True)
        return records

    candidates: list[tuple[int, str, Path]] = []
    max_seen_num = last_scanned
    with os.scandir(zh_img_dir) as it:
        for entry in it:
            if not entry.is_file():
                continue
            m = RE_HK_FILENAME.match(entry.name)
            if not m:
                continue
            num = int(m.group(1))
            if num > max_seen_num:
                max_seen_num = num
            if num > last_scanned and entry.name not in known_files:
                candidates.append((num, entry.name, Path(entry.path)))

    candidates.sort(key=lambda x: x[0])
    print(
        f"      Scanned dir {zh_img_dir}: last_scanned={last_scanned}, max_file={max_seen_num}, "
        f"new files to check={len(candidates)}",
        flush=True,
    )

    hires_new: list[tuple[int, str, int, int]] = []
    lowres_count = 0
    corrupt_count = 0
    for num, fname, fpath in candidates:
        try:
            with Image.open(fpath) as im:
                w, h = im.size
            if w >= min_width and h >= min_height:
                hires_new.append((num, fname, w, h))
            else:
                lowres_count += 1
        except Exception:
            corrupt_count += 1

    print(
        f"      Resolution check (>={min_width}x{min_height}): "
        f"hi-res={len(hires_new)}, low-res={lowres_count}, unreadable={corrupt_count}",
        flush=True,
    )

    if not hires_new:
        if max_seen_num > last_scanned:
            state["last_scanned_num"] = max_seen_num
            save_zh_cache(records, state)
        return records

    fetched_map: dict[int, dict[str, str]] = {}
    done = 0
    not_found = 0
    lock = threading.Lock()

    def worker(item: tuple[int, str, int, int]) -> tuple[int, str, int, int, dict[str, str] | None]:
        num, fname, w, h = item
        info = fetch_zh_card_detail(num, proxy=proxy)
        return num, fname, w, h, info

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, item) for item in hires_new]
        for fut in as_completed(futures):
            num, fname, w, h, info = fut.result()
            with lock:
                done += 1
                if info:
                    fetched_map[num] = {
                        "filename": fname,
                        "pack": info["pack"],
                        "id": info["id"],
                        "width": str(w),
                        "height": str(h),
                        "name": info["name"],
                        "illustrator": info["illustrator"],
                    }
                else:
                    not_found += 1
                if done % 50 == 0 or done == len(hires_new):
                    print(
                        f"      ZH detail [{done}/{len(hires_new)}] matched={len(fetched_map)}, not_found={not_found}",
                        flush=True,
                    )

    for num in sorted(fetched_map.keys()):
        records.append(fetched_map[num])

    state["last_scanned_num"] = max(last_scanned, max_seen_num)
    save_zh_cache(records, state)
    print(f"      ZH hi-res cache updated: total {len(records)} records.", flush=True)
    return records


# ---------------------------------------------------------------------------
# Step 4: Tiered ZH -> JP/EN group alignment
# ---------------------------------------------------------------------------

def load_zh_manual_map() -> dict[str, dict[str, dict[str, list[str]]]]:
    if not ZH_MANUAL_MAP_PATH.exists():
        return {"by_filename": {}, "by_pack_id": {}}
    with ZH_MANUAL_MAP_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "by_filename": data.get("by_filename", {}),
        "by_pack_id": data.get("by_pack_id", {}),
    }


def resolve_energy_groups(node_to_gid: dict[tuple[str, str, str], int]) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for code, anchors in ENERGY_ANCHORS.items():
        for anchor in anchors:
            if anchor in node_to_gid:
                resolved[code] = node_to_gid[anchor]
                break
    return resolved


def card_id_sort_key(cid: str) -> tuple[int, tuple[tuple[int, int | str], ...]]:
    """Natural sort key for card numbers: numeric-leading first, ascending by integer value."""
    m = RE_LEADING_INT.match(cid)
    group_rank = 0 if m else 1
    parts: list[tuple[int, int | str]] = []
    for tok in re.split(r"(\d+)", cid):
        if not tok:
            continue
        if tok.isdigit():
            parts.append((0, int(tok)))
        else:
            parts.append((1, tok.lower()))
    return (group_rank, tuple(parts))


def align_zh_to_groups(
    zh_records: list[dict[str, str]],
    cache: dict[str, Any],
    node_to_gid: dict[tuple[str, str, str], int],
) -> tuple[list[list[Any]], list[list[Any]]]:
    print("[4/4] Aligning ZH-HK hi-res cards to JP/EN group_ids (tiered)...", flush=True)
    manual = load_zh_manual_map()
    by_filename = manual["by_filename"]
    by_pack_id = manual["by_pack_id"]
    energy_gids = resolve_energy_groups(node_to_gid)

    ja_packs_in_db = {pack for (lang, pack, _cid) in node_to_gid if lang == "ja"}
    # Build pack release order from Limitless JP set list (oldest -> newest)
    ja_set_order = {s["code"]: idx for idx, s in enumerate(cache.get("ja_sets", []))}

    matched_rows: list[list[Any]] = []
    unmatched_rows: list[list[Any]] = []

    tier_counts = {"manual": 0, "energy": 0, "exact_ja": 0}
    unmatched_reasons: dict[str, int] = {}
    seen_filenames: set[str] = set()

    for rec in zh_records:
        fname = rec["filename"].strip()
        if not fname or fname in seen_filenames:
            continue
        seen_filenames.add(fname)

        pack = rec["pack"].strip()
        raw_id = rec["id"].strip()
        norm_id = raw_id.lstrip("0") or "0"
        name = rec.get("name", "").strip()
        illustrator = rec.get("illustrator", "").strip()

        gid: int | None = None

        # Tier 0: Explicit manual mapping
        manual_target = by_filename.get(fname) or by_pack_id.get(f"{pack}:{norm_id}") or by_pack_id.get(f"{pack}:{raw_id}")
        if isinstance(manual_target, dict):
            if "ja" in manual_target and len(manual_target["ja"]) == 2:
                gid = node_to_gid.get(("ja", str(manual_target["ja"][0]), str(manual_target["ja"][1])))
            elif "en" in manual_target and len(manual_target["en"]) == 2:
                gid = node_to_gid.get(("en", str(manual_target["en"][0]), str(manual_target["en"][1])))
            if gid is not None:
                tier_counts["manual"] += 1

        # Tier 1: Basic Energy
        if gid is None and raw_id.upper() in energy_gids:
            gid = energy_gids[raw_id.upper()]
            tier_counts["energy"] += 1

        # Tier 2: Direct match for regular JP expansions / matching sets (excluding Promos)
        if gid is None:
            is_promo = pack in ZH_PROMO_PACKS or pack.endswith("-P")
            if is_promo:
                reason = "promo_needs_manual"
            elif pack not in ja_packs_in_db:
                reason = "pack_not_in_ja"
            else:
                gid = node_to_gid.get(("ja", pack, norm_id)) or node_to_gid.get(("ja", pack, raw_id))
                if gid is not None:
                    tier_counts["exact_ja"] += 1
                    reason = ""
                else:
                    reason = "id_not_in_ja"

            if gid is None:
                unmatched_reasons[reason] = unmatched_reasons.get(reason, 0) + 1
                unmatched_rows.append([fname, pack, norm_id, name, illustrator, reason])
                continue

        matched_rows.append([pack, norm_id, fname, gid])

    # Sort ZH rows strictly by JP set release order (newest -> oldest, Promo before era sets) then card id asc
    def zh_sort_key(row: list[Any]) -> tuple[int, tuple[int, tuple[tuple[int, int | str], ...]]]:
        pack, cid = row[0], row[1]
        set_idx = ja_set_order.get(pack, -1)
        return (-set_idx, card_id_sort_key(cid))

    matched_rows.sort(key=zh_sort_key)
    unmatched_rows.sort(key=lambda r: (r[5], r[1], card_id_sort_key(r[2])))

    print(
        f"      ZH matched: {len(matched_rows)} "
        f"(manual={tier_counts['manual']}, energy={tier_counts['energy']}, exact_ja={tier_counts['exact_ja']}) | "
        f"unmatched: {len(unmatched_rows)} {unmatched_reasons}",
        flush=True,
    )
    return matched_rows, unmatched_rows


def build_sets_rows(cache: dict[str, Any]) -> list[list[Any]]:
    """Build sets.csv rows ordered newest -> oldest (Promo after era sets) per region."""
    rows: list[list[Any]] = []
    for region, sets_key, lang in (("en-US", "en_sets", "en"), ("ja-JP", "ja_sets", "ja")):
        sets_newest_first = list(reversed(cache.get(sets_key, [])))
        bucket = cache.get(lang, {})
        for order_idx, s in enumerate(sets_newest_first):
            code = s["code"]
            cached_cards = bucket.get(code, {}).get("cards", [])
            card_count = s.get("card_count") or len(cached_cards)
            rows.append(
                [
                    region,
                    code,
                    s.get("name", ""),
                    s.get("era", ""),
                    normalize_release_date(s.get("release_date", "")),
                    card_count,
                    order_idx,
                ]
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental PTCG card database synchronizer.")
    parser.add_argument("--skip-limitless", action="store_true", help="Reuse cached limitless_cache.json without fetching.")
    parser.add_argument("--skip-zh-scan", action="store_true", help="Reuse cached zh_hidpi_cache.csv without scanning images.")
    parser.add_argument("--force-all", action="store_true", help="Re-fetch all EN & JP sets from Limitless.")
    parser.add_argument("--force-sets", default="", help="Comma-separated set codes to re-fetch (e.g. M7,MEP,MP).")
    parser.add_argument("--rescan-zh-all", action="store_true", help="Rescan entire ZH image directory for missed hi-res files.")
    parser.add_argument("--zh-img-dir", type=Path, default=DEFAULT_ZH_IMG_DIR, help="Path to local ZH-HK PNG dump folder.")
    parser.add_argument("--zh-seed-csv", type=Path, default=DEFAULT_ZH_SEED_CSV, help="Historical zh_hidpi.csv for initial seeding.")
    parser.add_argument("--min-width", type=int, default=736, help="Min pixel width for ZH hi-res.")
    parser.add_argument("--min-height", type=int, default=1024, help="Min pixel height for ZH hi-res.")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent worker count for Limitless.")
    parser.add_argument("--zh-workers", type=int, default=2, help="Concurrent worker count for HK official site.")
    parser.add_argument("--proxy", default=None, help="Optional HTTP/HTTPS proxy URL (e.g. http://127.0.0.1:7890).")
    args = parser.parse_args()

    DB_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    cache = load_limitless_cache()
    if not args.skip_limitless:
        force_set_codes = {s.strip() for s in args.force_sets.split(",") if s.strip()}
        cache = sync_limitless(
            cache,
            workers=args.workers,
            force_all=args.force_all,
            force_sets=force_set_codes,
            proxy=args.proxy,
        )

    en_rows, ja_rows, node_to_gid = build_en_ja_groups(cache)

    if args.skip_zh_scan:
        seed_zh_cache_if_needed(args.zh_seed_csv)
        zh_records, _ = load_zh_cache()
    else:
        zh_records = scan_zh_incremental(
            zh_img_dir=args.zh_img_dir,
            seed_csv=args.zh_seed_csv,
            min_width=args.min_width,
            min_height=args.min_height,
            workers=args.zh_workers,
            rescan_all=args.rescan_zh_all,
            proxy=args.proxy,
        )

    zh_rows, zh_unmatched = align_zh_to_groups(zh_records, cache, node_to_gid)

    sets_rows = build_sets_rows(cache)
    atomic_write_csv(
        SETS_CSV_PATH,
        ["region", "code", "name", "era", "release_date", "card_count", "order"],
        sets_rows,
    )
    atomic_write_csv(EN_CSV_PATH, ["pack", "id", "name", "group", "url"], en_rows)
    atomic_write_csv(JA_CSV_PATH, ["pack", "id", "name", "group", "url"], ja_rows)
    atomic_write_csv(ZH_CSV_PATH, ["pack", "id", "filename", "group"], zh_rows)
    atomic_write_csv(
        ZH_UNMATCHED_PATH,
        ["filename", "pack", "id", "name", "illustrator", "reason"],
        zh_unmatched,
    )

    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s! Wrote sets.csv, en_data.csv, ja_data.csv, zh_data.csv, zh_unmatched.csv.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
