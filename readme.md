# A Printable PTCG Card Layout Generator

Managed with [`uv`](https://docs.astral.sh/uv/).

## Quick Start

1. Install dependencies (creates `.venv` automatically):
   ```bash
   uv sync
   ```
2. Launch the GUI:
   ```bash
   uv run gui.py
   ```

## Database Maintenance

Run the incremental database synchronizer to fetch new EN/JP sets from Limitless TCG, compute collision-free global `group` IDs via Union-Find, scan newly dumped ZH-HK hi-res images (`>= 736x1024`), and rebuild `database/{en,ja,zh}_data.csv`:

```bash
uv run database/sync_db.py
```

Useful options:
- `--skip-limitless`: skip Limitless network requests and rebuild from local cache.
- `--skip-zh-scan`: skip scanning `E:\PTCG_zh-Hant` and fetching HK detail pages.
- `--force-sets M7,MEP,MP`: force re-fetching specific sets.
- `--zh-img-dir <path>`: override local ZH-HK image dump directory (default `E:\PTCG_zh-Hant`).
- `--proxy http://127.0.0.1:7890`: specify an explicit proxy URL if needed.

Unmatched ZH-HK promos / region-exclusive decks are exported to `database/zh_unmatched.csv`. Add desired overrides to `database/zh_manual_map.json` and re-run `uv run database/sync_db.py --skip-limitless --skip-zh-scan` to apply immediately.
