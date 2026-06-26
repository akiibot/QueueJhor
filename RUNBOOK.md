# RUNBOOK — QueueStorm Investigator

A stranger should be able to bring this service up by copy-pasting from here.
No environment variables are required; the service runs fully in rules-only mode.

---

## 1. Run locally (Python 3.11+)

```bash
git clone <your-repo-url>
cd queuestorm-investigator

python3.11 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/analyze-ticket \
  -H 'content-type: application/json' \
  -d '{"ticket_id":"TKT-001","complaint":"I sent 5000 taka to a wrong number around 2pm today.","transaction_history":[{"transaction_id":"TXN-9101","timestamp":"2026-04-14T14:08:22Z","type":"transfer","amount":5000,"counterparty":"+8801719876543","status":"completed"}]}'
```

---

## 2. Run with Docker

```bash
docker build -t queuestorm-team .
docker run -p 8000:8000 queuestorm-team
```

The container binds to `0.0.0.0:8000` (override with `-e PORT=...`). Image is
based on `python:3.11-slim` with only pure-Python dependencies — comfortably
under the 500 MB recommendation.

With the optional LLM polish:

```bash
docker run -p 8000:8000 --env-file judging.env queuestorm-team
# judging.env contains: USE_LLM=true and ANTHROPIC_API_KEY=...
```

---

## 3. Deploy to a live URL

Any host that can run a container or a Python process works (Render, Railway,
Fly.io, a Poridhi Lab VM, EC2, …). General recipe:

1. Push this repo to your platform / point it at the `Dockerfile`.
2. Ensure the start command is:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Confirm **no** auth/login/password protection sits in front of the service —
   the judge calls it directly.
4. From outside the host, verify both endpoints respond:
   ```bash
   curl https://<your-url>/health
   curl -X POST https://<your-url>/analyze-ticket -H 'content-type: application/json' -d '{"ticket_id":"T","complaint":"test"}'
   ```

### Example: Render

- New → Web Service → connect repo.
- Environment: Docker (uses the included `Dockerfile`).
- No environment variables needed (add `USE_LLM` / `ANTHROPIC_API_KEY` only if
  you want LLM polish — set them in Render's dashboard, never in the repo).

---

## 4. Environment variables (all optional)

| Variable            | Default                      | Purpose                                  |
|---------------------|------------------------------|------------------------------------------|
| `PORT`              | `8000`                       | Port to bind.                            |
| `USE_LLM`           | `false`                      | Enable optional LLM polish of text.      |
| `ANTHROPIC_API_KEY` | _(empty)_                    | Required only when `USE_LLM=true`.       |
| `LLM_MODEL`         | `claude-haiku-4-5-20251001`  | Polish model.                            |
| `LLM_TIMEOUT`       | `8`                          | Seconds before falling back to templates.|

Secrets are read from the environment only. Never commit a real key; see
`.env.example`.

---

## 5. Run the tests

```bash
pip install pytest
python -m pytest -q
```

## 6. Regenerate the sample output file

```bash
python scripts/gen_sample_output.py   # writes sample_output.json
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 404 on endpoints | Use exact paths `/health` and `/analyze-ticket`. |
| Works locally, judge can't reach it | Bind to `0.0.0.0`, expose the right port, remove any login wall. |
| Bangla shows as `\uXXXX` | The service returns UTF-8 JSON; ensure your client/terminal renders UTF-8. |
| LLM-related errors | Set `USE_LLM=false` (default) — the service is fully functional without it. |
