MLFLOW_TRACKING_URI ?= http://localhost:5000
CODEX_EXPERIMENT    ?= codex-traces
CLAUDE_EXPERIMENT   ?= claude-traces

# ─────────────────────────────────────────────
# セットアップ
# ─────────────────────────────────────────────

.PHONY: setup
setup: patch uv-sync
	@echo ""
	@echo "✓ セットアップ完了"
	@echo ""
	@echo "次のステップ: ~/.codex/config.toml に以下を追加してください"
	@echo '  notify = ["mlflow-codex", "notify-hook"]'
	@echo ""
	@echo "MLflow サーバーの向き先を設定 (~/.codex/mlflow-tracing.json):"
	@echo '  {"trackingUri": "$(MLFLOW_TRACKING_URI)", "experimentId": "0"}'

.PHONY: patch
patch:
	npm install -g @mlflow/codex@0.2.0-rc.0
	npm install

.PHONY: uv-sync
uv-sync:
	uv sync

# ─────────────────────────────────────────────
# MLflow サーバー (Docker)
# ─────────────────────────────────────────────

.PHONY: server
server:
	docker compose up -d
	@echo "MLflow UI: http://localhost:5000"

.PHONY: server-stop
server-stop:
	docker compose down

.PHONY: server-logs
server-logs:
	docker compose logs -f

# ─────────────────────────────────────────────
# インポート (バッチ)
# ─────────────────────────────────────────────

.PHONY: import
import:
	uv run mlflow-codex import-latest \
	  --tracking-uri $(MLFLOW_TRACKING_URI) \
	  --experiment $(CODEX_EXPERIMENT)

.PHONY: import-claude
import-claude:
	uv run mlflow-codex import-claude-latest \
	  --tracking-uri $(MLFLOW_TRACKING_URI) \
	  --experiment $(CLAUDE_EXPERIMENT)

# ─────────────────────────────────────────────
# ローカル UI (sqlite)
# ─────────────────────────────────────────────

.PHONY: ui
ui:
	uv run mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5000
