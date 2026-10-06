# Streamlit Clean

MyEmailVerifier email list cleaner → Instantly campaign push.

## Quick start

From repo root (see [`Makefile`](../Makefile)):

```bash
make venv
make dev-clean
```

Or manually:

```bash
cd clean
pip install -r requirements.txt
streamlit run app.py
```

### Headless CLI

```bash
export PYTHONPATH=/path/to/scrapper-cleaner:/path/to/scrapper-cleaner/clean
cd clean
python cli.py credits
python cli.py export-mev --list-id <uuid> -o mev_emails.csv
python cli.py audit-list --list-id <uuid>
python cli.py run --list-id <uuid> --campaign-id <uuid> --mode test_50
python cli.py checkpoints
```

Copy [`.env.example`](../.env.example) to repo root `.env` before running.

## Environment

Requires in repo root `.env`:

| Variable | Purpose |
|----------|---------|
| `MYEMAILVERIFIER_API_KEY` | Bulk email verification |
| `INSTANTLY_API_KEY` | List fetch, purge, campaign push |

## Pipeline

1. Select source Instantly list
2. Select target campaign
3. Choose run mode (dry / test-50 / full / custom)
4. Execute: quick pre-filter → MyEmailVerifier → optional list purge → push valid leads
5. Review results; workspace duplicate check always on during push
6. Final-clean rows are marked `status=cleaned` on the central Supabase `leads` table (no-op when Supabase is not configured). Instantly receives `phone`, `category`, `status`, and `cleaned` only.

## MyEmailVerifier CSV format

MyEmailVerifier reads the **first column** of uploaded files. Use a single-column CSV:

```csv
email
user@example.com
```

- **Do not** upload Instantly UI exports (first column is `id`, not email).
- Use **Download for MEV** in step 1, or `python cli.py export-mev --list-id <uuid>`.
- The pipeline builds `{prefix}_mev_upload_0.csv` automatically during verification.

## Checkpoint recovery

Interrupted runs can resume via checkpoint UI. See `checkpoint.py` and `recover_checkpoint.py`.
