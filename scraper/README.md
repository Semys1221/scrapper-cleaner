# Scraper (Streamlit UI + headless workers)

**Headless workers** run from the repo root via `python main.py` (`worker-loop`, `heal`, `scrape`, `push-instantly`, …). Data is written under `$HERCULE_DATA_ROOT/streamlit_scraper/output/<preset>/` (default on VPS: `/var/lib/hercule`).

The Streamlit app is a dashboard to **read scrape history** (VPS SSH + optional n8n API) and **trigger scrapes** via n8n webhook.

## Run locally

```bash
cd scraper && streamlit run app.py
```

Or from repo root: `make dev-scraper`

## Presets

Niche settings are in `presets.yaml` (migrated from the former `configs/*_config.py` modules). The UI loads `TARGET_LEADS`, `TARGET_MODE`, and Instantly IDs for display and launch guards.

## Environment

| Variable | Purpose |
|----------|---------|
| `VPS_HOST`, `VPS_USER` | SSH read of `scrape_state.json`, `scrape.log`, heartbeat under `HERCULE_DATA_ROOT` |
| `VPS_SSH_PASSWORD` or `VPS_SSH_KEY` | SSH authentication |
| `HERCULE_DATA_ROOT` | Remote data root (default on VPS: `/var/lib/hercule`) |
| `VPS_SCRAPER_SERVICE` | systemd unit for the scraper worker (stopped internally when you **Archiver le scrape** in the UI) |
| `N8N_SCRAPE_WEBHOOK_URL` | **POST** `{ "keyword", "instantly_list_id", "target_leads", "preset_id?" }` → n8n writes `/var/lib/hercule/scraper-env/<preset>.env` on VPS, reloads systemd drop-in, runs `main.py heal --preset <id>` (default preset: `SCRAPE_DEFAULT_PRESET` / `N8N_DEFAULT_PRESET` / `_adhoc`) |
| `N8N_BASE_URL`, `N8N_API_KEY` | Optional read-only execution history |
| `INSTANTLY_API_KEY` | Injected into preset config for UI checks |
| `INSTANTLY_LIST_ID_<PRESET>` | Per-preset list override (see `config_loader.py`) |

See repo `.env.example` for a full template.

## Data paths

Per preset: `$HERCULE_DATA_ROOT/streamlit_scraper/output/{preset_id}/` — `scrape_state.json`, `scrape.log`, `worker_heartbeat.json`, `cron_events.jsonl`, CSV exports (written by `main.py worker-loop`).

## Running the workers on the VPS

Install deps at repo root (`pip install -r requirements.txt`), copy `.env` from `.env.example`, set `HERCULE_DATA_ROOT=/var/lib/hercule`, `OUTSCRAPER_API_KEY`, `INSTANTLY_API_KEY`, and per-preset `INSTANTLY_LIST_ID_<PRESET>` (or values in `presets.yaml`).

Example systemd units (adjust `WorkingDirectory` and `EnvironmentFile` to your checkout):

**Avocats worker** — exits cleanly when target is reached; use `Restart=on-failure` so a successful stop does not loop forever:

```ini
[Service]
WorkingDirectory=/root/scrapper-cleaner
EnvironmentFile=/root/scrapper-cleaner/.env
ExecStart=/usr/bin/python3 main.py worker-loop --preset avocats --push-instantly
Restart=on-failure
RestartSec=30
```

**Avocats heal cron** (every minute via timer or cron):

```ini
ExecStart=/usr/bin/python3 main.py heal --preset avocats --stale-minutes 3
```

**Agences immobilières** — same pattern with `--preset agences_immobilieres` and a dedicated `VPS_SCRAPER_SERVICE` / unit name if you run multiple presets.

`heal` reads `VPS_SCRAPER_SERVICE` (default `hercule-scraper`) and restarts that unit when the worker heartbeat is stale and progress is below `TARGET_LEADS`.

## Central leads and phone enrichment

Scraped rows are upserted to Supabase `public.leads` (table owned by hercule.dev) with `status=uncleaned` and a one-word `category` such as `PLOMBIER`. The unique key is the normalized email (`lower(trim(email))`). A repeat scrape keeps the existing status and category and only fills empty phone, website, name, and company fields. Uncleaned leads are not pushed to Instantly unless `HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH=1`.

After the cleaner marks rows `cleaned`, retrieve verified phones (no production run unless you pass `--execute`):

```bash
python main.py enrich-phones --preset plombier --limit 1000
python main.py enrich-phones --preset plombier --limit 1000 --execute
```

Budget **$8 per 1,000 leads** at Outscraper medium-tier rates ($3 emails-and-contacts + $5 phones-enricher) when every lead needs a lookup and yields one number. The first 500 domains and 25 phones each month are free.
