# API Traffic Replay Debugger

Record a set of HTTP requests against one API, replay those same requests against another, and get a deterministic report of what changed.

The replay engine is a library and a `replay` command. It does not need a database, an account, or a model. A later service can store the report, and a model can explain the diffs, but neither one decides whether the API regressed.

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

On macOS or Linux, activate the virtualenv with `source .venv/bin/activate` instead. The commands below assume the virtualenv is active, so `replay` is on `PATH`. `python -m replay_core.cli` is the same program.

## Record and replay

`replay record` sends a request file and writes a baseline. `replay run` sends that file again, compares the new responses to the baseline, and writes a report.

```powershell
replay record --target http://127.0.0.1:8001/v1 --requests requests.json --out baseline.json
replay run --target http://127.0.0.1:8001/v2 --requests requests.json --baseline baseline.json --out report.json
```

Exit codes:

- `0` means every request matched
- `1` means at least one regression or transport error, including a timeout
- `2` means the command itself was invalid, such as a bad file or a mutating request without `--unsafe`

`--concurrency` defaults to 10. `--timeout` defaults to 10 seconds per request. `--format json` prints the report to stdout as well as writing `--out`. The report file is always JSON.

`replay run` follows request order in the report even when responses finish out of order. Redirects are not followed, so a new `302` shows up as a status change. The client does not read `HTTP_PROXY` from the environment; the `--target` URL is the URL that is called.

## Request file

Paths are joined onto `--target`. `http://127.0.0.1:8001/v1` plus `/health` is `http://127.0.0.1:8001/v1/health`. A request may set `json` or `body`, not both. Unknown fields are rejected so a typo does not silently disappear.

```json
{
  "name": "orders",
  "ignore": ["id", "created_at", "items.*.id"],
  "requests": [
    {
      "id": "create-order",
      "method": "POST",
      "path": "/orders",
      "headers": {"content-type": "application/json"},
      "json": {"sku": "A", "qty": 1}
    }
  ]
}
```

`ignore` entries are dotted paths. `*` matches one segment. A pattern ignores that node and everything under it, so `user` ignores `user.name`, and `items.*.id` ignores each element's `id` without ignoring `items.0.name`. Array order is significant. Object key order is not. `true` and `1` are different values. `1` and `1.0` compare equal, because both are numbers.

Requests are independent. The engine does not copy an id from one response into the next request.

## Comparison

Status codes are always compared. JSON bodies are parsed and compared structurally, so whitespace and key order are not regressions. Anything that is not JSON is compared as bytes. Header names are case-insensitive.

These headers are removed before a baseline is saved and ignored again during compare:

- secrets: `authorization`, `cookie`, `set-cookie`
- hop identity: `date`, `server`
- transfer metadata: `content-length`, `transfer-encoding`, `connection`

`content-type` is still compared. `content-length` is not, because two equivalent JSON bodies can have different sizes once formatting changes, and the body diff already covers the payload.

## Safety

`GET` and `HEAD` run as they are. `POST`, `PUT`, `PATCH`, and `DELETE` require `--unsafe`, because replaying them can create or delete real data. Record and replay against a disposable API. Do not commit live tokens in a request file; the tool redacts those headers on the way out, and it does not rewrite the request file you already wrote.

## Report

Each result is `matched`, `regressed`, or `errored`. A diff's `kind` is `status`, `header`, `json`, or `body`. `op` is `replace`, `add`, or `remove`, which keeps a removed field distinct from a field whose value is JSON `null`.

Text output lists failures only. This is the real v1-to-v2 run of the demo below:

```text
demo: 3 total, 1 matched, 2 regressed, 0 errored

REGRESSED health GET /health
  status: 200 -> 500
  json status: "ok" -> "down"

REGRESSED order GET /order
  json product_sku: <missing> -> "A"
  json sku: "A" -> <missing>
```

`clock` is the matched request, so it does not appear in the detail list. The JSON file is the contract. Later storage, a dashboard, or a model should read that file instead of comparing HTTP bodies again.

## Demo

`examples/demo_api` is a small FastAPI app with a stable `/v1` and a `/v2` that breaks in known ways. From the repo root, with the dev extra installed:

```powershell
uvicorn app:app --app-dir examples/demo_api --port 8001
```

In another shell:

```powershell
replay record --target http://127.0.0.1:8001/v1 --requests examples/demo_api/requests.json --out baseline.json
replay run --target http://127.0.0.1:8001/v2 --requests examples/demo_api/requests.json --baseline baseline.json --out report.json
```

`/v1/health` sets a `Set-Cookie` header. The baseline file should not contain that cookie. The replay prints the report in the previous section and exits 1. `/clock` returns a different `created_at` on v2 and is the match, because the request file ignores `created_at`. `/order` renames `sku` to `product_sku`. `/health` changes from 200 to 500.

## Benchmark

`benchmarks/concurrency_bench.py` starts the demo API and replays 50 calls to `GET /delay?ms=20`. That route waits 20ms without blocking a worker. Reported latency includes time waiting for a free concurrency slot.

```powershell
python benchmarks/concurrency_bench.py
```

Results from one run on this Windows machine:

| concurrency | throughput | p50 latency | p95 latency | wall time |
| --- | ---: | ---: | ---: | ---: |
| 1 | 24.2 req/s | 958.8 ms | 1668.7 ms | 2065.8 ms |
| 10 | 39.9 req/s | 360.0 ms | 580.0 ms | 1254.6 ms |
| 50 | 37.0 req/s | 391.7 ms | 552.2 ms | 1351.5 ms |

With one request in flight, the median call sits behind about half the queue, so its latency is close to half the run. Allowing 10 at a time raises throughput and cuts that median. At 50, throughput stays near the concurrency-10 result: the server wait is only 20ms, so once several calls overlap, local socket and process overhead dominates. A unit test checks that in-flight work stops at the configured cap.

## Hosted API (optional)

The local engine still works offline. The hosted API stores projects, request collections, baselines, runs, and the report JSON. It does not re-compare responses.

Start Postgres and the API:

```powershell
docker compose up --build
```

Or run the API against a local Postgres after copying `.env.example` to `.env`:

```powershell
pip install -e ".[dev]"
uvicorn replay_api.main:app --reload --port 8000
```

Create a project, then upload a report:

```powershell
replay projects create --api-url http://127.0.0.1:8000 --name demo
replay upload --api-url http://127.0.0.1:8000 --token TOKEN --project-id PROJECT_ID --report report.json --requests examples/demo_api/requests.json --baseline baseline.json --target http://127.0.0.1:8001/v2
```

`projects create` prints a token once. The database stores only a hash of that token. Requests use `Authorization: Bearer <token>`.

API shape under `/v1`:

- `POST /projects` creates a project
- `POST /projects/{id}/collections` stores a request file
- `POST /projects/{id}/baselines` stores a baseline
- `POST /projects/{id}/runs` stores a report and summary counts
- `GET /projects/{id}/runs` lists run summaries
- `GET /projects/{id}/runs/{run_id}` returns the stored report (and diagnosis if present)
- `POST /projects/{id}/runs/{run_id}/diagnose` asks the model to explain regressions
- `GET /projects/{id}/runs/{run_id}/diagnosis` returns a stored diagnosis

pytest uses a temporary SQLite database, so the suite does not require Docker.

## AI diagnosis

The engine still decides what changed. Diagnosis only narrates the **regression subset** of a stored report. Matched cases and full response bodies are not sent to the model. Live calls stay off unless both are set in `.env`:

```env
LLM_ENABLED=true
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

Without that configuration, `POST .../diagnose` returns 503. Tests inject a fake provider and never call a real model.

```powershell
replay diagnose --api-url http://127.0.0.1:8000 --token TOKEN --project-id PROJECT_ID --run-id RUN_ID
```

On the run detail page, use **Explain regressions** to generate or refresh the stored diagnosis.

## Dashboard

`web/` is a React + TypeScript UI that lists runs and renders the stored diff list. It does not re-compare responses.

With the API running on port 8000:

```powershell
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173, paste the project id and token from `replay projects create`, then open a run. Vite proxies `/v1` to the API.

To serve the built UI from FastAPI itself:

```powershell
cd web
npm run build
uvicorn replay_api.main:app --reload --port 8000
```

Then open http://127.0.0.1:8000 after creating a project and uploading a report.

## HAR import

Chrome, Firefox, and Postman can export a HAR file. Import it into the request-file schema (authorization and cookie headers are stripped):

```powershell
replay import-har --har examples/demo_api/sample.har --out requests.json --name demo --base-url http://127.0.0.1:8001/v1
```

`--base-url` stores paths relative to that prefix (`/v1/health` becomes `/health` when the base is `.../v1`). Without it, the full URL path is kept. The importer does not replay anything; it only writes JSON for `record` / `run`.

## GitHub Action

[`.github/actions/replay-run`](.github/actions/replay-run) is a composite action that installs the package, runs `replay run`, and optionally uploads with a project API token. Exit code `1` fails the job when there is a regression.

```yaml
- uses: ./.github/actions/replay-run
  with:
    target: https://staging.example.com
    requests: requests.json
    baseline: baseline.json
    report: report.json
    upload: "true"
    api-url: https://replay.example.com
    project-id: ${{ vars.REPLAY_PROJECT_ID }}
    api-token: ${{ secrets.REPLAY_API_TOKEN }}
```

See [`.github/workflows/replay-ci.example.yml`](.github/workflows/replay-ci.example.yml) for a full copy-paste workflow. The example filename keeps GitHub from running it until you rename it.

## Layout

```text
src/replay_core/              library and CLI (including HAR import)
src/replay_api/               FastAPI service (stores reports, does not re-diff)
web/                          React + TypeScript dashboard
tests/                        unit, CLI, and API tests
examples/demo_api/            disposable v1/v2 API + sample HAR
.github/actions/replay-run/   composite action for CI replay + upload
benchmarks/                   concurrency measurement
docker-compose.yml            Postgres + API
```

`compare.py` has no I/O. `runner.py` is the only module that sends replay HTTP. HAR import only translates files. The hosted API and dashboard only persist and display JSON the CLI already produced.
