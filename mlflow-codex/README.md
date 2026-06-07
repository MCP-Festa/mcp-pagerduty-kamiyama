# mlflow-codex

Records Codex CLI and Claude Code sessions as MLflow traces.

Creates one MLflow trace per session.

**Codex sessions** (`~/.codex/sessions/**/*.jsonl`):
- user prompts and assistant messages
- session metadata: CLI version, model provider, cwd, model name
- tool calls with arguments and outputs
- MCP tool classification (e.g. `mcp__filesystem__read_text_file`)

**Claude Code sessions** (`~/.claude/projects/**/*.jsonl`):
- user prompts and assistant text
- AI-generated session title and model name
- tool calls (including MCP tools) with inputs and outputs
- per-turn token usage (input, output, cache read, cache creation)
- turn durations

Import is not automatic. Run the import command after each Codex or Claude Code session.

---

## Quick Start

### 1. Setup

```bash
make setup
```

Installs `@mlflow/codex` globally, applies the bug-fix patch, and syncs Python dependencies.

Then configure Codex to call the notify hook (`~/.codex/config.toml`):
```toml
notify = ["mlflow-codex", "notify-hook"]
```

Point the hook at your MLflow server (`~/.codex/mlflow-tracing.json`):
```json
{
  "trackingUri": "http://<mlflow-server>:5000",
  "experimentId": "0"
}
```

### 2. Start MLflow server (Docker)

```bash
make server
```

Starts at `http://localhost:5000`. Stop with `make server-stop`.

### 3. Import sessions

```bash
make import          # latest Codex session
make import-claude   # latest Claude Code session
```

---

## Make targets

| Target | Description |
|---|---|
| `make setup` | Install, patch, and sync dependencies in one step |
| `make patch` | Install `@mlflow/codex` and apply the bug-fix patch |
| `make server` | Start MLflow server via Docker |
| `make server-stop` | Stop the Docker server |
| `make server-logs` | Follow server logs |
| `make import` | Import the latest Codex session |
| `make import-claude` | Import the latest Claude Code session |
| `make ui` | Start MLflow UI against the local SQLite DB |

Override the server URL with an environment variable:

```bash
make import MLFLOW_TRACKING_URI=http://192.168.1.10:5000
```

---

## What the `@mlflow/codex` patch fixes

The patch (`scripts/patch-mlflow-codex.mjs`) corrects the following issues in `@mlflow/codex@0.2.0-rc.0`:

- `input-messages` split character-by-character when passed as a string
- trace inputs/outputs not stored as proper JSON objects
- assistant response not correctly restored from transcript
- TOOL spans not nested under their triggering LLM span in the MLflow UI waterfall view
- spans not written to the tracking DB via OTLP, causing "No trace data available" in the detailed trace view

All network traffic goes only to the `trackingUri` you configure. No external endpoints.

---

## Batch import (details)

```bash
# Latest Codex session
uv run mlflow-codex import-latest \
  --tracking-uri sqlite:///mlflow.db \
  --experiment codex-traces

# Latest Claude Code session
uv run mlflow-codex import-claude-latest \
  --tracking-uri sqlite:///mlflow.db \
  --experiment claude-traces

# Specific session file
uv run mlflow-codex import ~/.codex/sessions/2026/05/30/rollout-....jsonl \
  --tracking-uri sqlite:///mlflow.db \
  --experiment codex-traces
```

Open the UI:

```bash
make ui
```

Then open `http://127.0.0.1:5000` and check the **Traces** tab.

## Prompt capture

By default all base instructions, user prompts, and assistant messages are recorded.
For a lighter or more privacy-conscious trace:

```bash
uv run mlflow-codex import-latest --no-base-instructions --max-value-chars 8000
```

Common secret fields (`api_key`, `token`, `password`, `authorization`, `cookie`) are
redacted recursively before being sent to MLflow.

## Notes

Codex session timestamps are preserved as span attributes (`codex.timestamp`,
`codex.started_at`, `codex.ended_at`). MLflow span timing reflects import time because
the manual tracing API creates live spans.
