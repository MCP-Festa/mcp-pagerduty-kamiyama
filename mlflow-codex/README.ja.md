# mlflow-codex

Codex CLI および Claude Code のセッション JSONL ファイルを MLflow トレースとして記録するツールです。

セッションごとに1つの MLflow トレースを作成します。

**Codex セッション** (`~/.codex/sessions/**/*.jsonl`):
- ユーザープロンプトとアシスタント応答
- CLI バージョン・モデルプロバイダー・cwd・モデル名などのセッションメタデータ
- ツール呼び出し（引数と出力）
- `mcp__filesystem__read_text_file` のような MCP ツール名の分類

**Claude Code セッション** (`~/.claude/projects/**/*.jsonl`):
- ユーザープロンプトとアシスタントテキスト
- AI 生成のセッションタイトルとモデル名
- ツール呼び出し（MCP ツール含む、入力と出力）
- ターンごとのトークン使用量（input / output / cache read / cache creation）
- ターン所要時間

インポートは自動では行われません。Codex または Claude Code の実行後、手動でインポートコマンドを実行してください。

---

## クイックスタート

### 1. セットアップ

```bash
make setup
```

`@mlflow/codex` のグローバルインストール・パッチ適用・Python 依存関係の同期を一括で実行します。

完了後、表示される指示に従って以下を設定してください。

**Codex の notify hook 設定** (`~/.codex/config.toml`):
```toml
notify = ["mlflow-codex", "notify-hook"]
```

**MLflow トラッキング URI の設定** (`~/.codex/mlflow-tracing.json`):
```json
{
  "trackingUri": "http://<mlflow-server>:5000",
  "experimentId": "0"
}
```

### 2. MLflow サーバーを起動（Docker）

```bash
make server
```

`http://localhost:5000` で起動します。停止は `make server-stop`。

### 3. セッションをインポート

```bash
make import          # 最新の Codex セッション
make import-claude   # 最新の Claude Code セッション
```

---

## make コマンド一覧

| コマンド | 説明 |
|---|---|
| `make setup` | インストール・パッチ・依存関係を一括セットアップ |
| `make patch` | `@mlflow/codex` をインストールしてパッチを適用 |
| `make server` | Docker で MLflow サーバーを起動 |
| `make server-stop` | Docker サーバーを停止 |
| `make server-logs` | サーバーログをフォロー |
| `make import` | 最新の Codex セッションをインポート |
| `make import-claude` | 最新の Claude Code セッションをインポート |
| `make ui` | ローカルの SQLite DB で MLflow UI を起動 |

送信先サーバーは環境変数で上書き可能です:

```bash
make import MLFLOW_TRACKING_URI=http://192.168.1.10:5000
```

---

## `@mlflow/codex` パッチの内容

Codex CLI の notify-hook 経由でリアルタイムにトレースを記録するために、以下のバグ・制限を修正しています。

- `input-messages` が文字列のとき1文字ずつ分解されてしまうバグを修正
- トレースの inputs/outputs を正しい JSON オブジェクト形式で保存するよう修正
- transcript からアシスタント応答を正しく復元するよう修正
- TOOL スパンを対応する LLM スパンの子として階層化（MLflow UI でのネスト表示）
- スパンを OTLP 経由で DB に書き込み、MLflow UI の「詳細トレースビュー」でツール呼び出しが表示されるよう修正

---

## バッチインポート（詳細）

### 最新の Codex セッション

```bash
uv run mlflow-codex import-latest \
  --tracking-uri sqlite:///mlflow.db \
  --experiment codex-traces
```

### 最新の Claude Code セッション

```bash
uv run mlflow-codex import-claude-latest \
  --tracking-uri sqlite:///mlflow.db \
  --experiment claude-traces
```

### 特定のセッション

```bash
uv run mlflow-codex import ~/.codex/sessions/2026/05/30/rollout-....jsonl \
  --tracking-uri sqlite:///mlflow.db \
  --experiment codex-traces

uv run mlflow-codex import-claude ~/.claude/projects/<project>/<uuid>.jsonl \
  --tracking-uri sqlite:///mlflow.db \
  --experiment claude-traces
```

MLflow UI を開く:

```bash
make ui
# または
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5000
```

`http://127.0.0.1:5000` を開いて **Traces** タブを確認してください。

---

## プロンプトの記録について

デフォルトでは Codex のベース指示・ユーザープロンプト・アシスタント応答をすべて記録します。
軽量にしたい場合や機密情報を含む場合は以下のオプションを使用してください:

```bash
uv run mlflow-codex import-latest --no-base-instructions --max-value-chars 8000
```

`api_key`、`token`、`password`、`authorization`、`cookie` などの一般的な機密フィールドは MLflow に送信する前に再帰的にマスクされます。

Codex は一部の MCP 呼び出しをツール名のみで記録する場合があります。`list_hosts`、`list_items`、`list_triggers`、`get_active_problems` などの Zabbix MCP ツールは `mcp.zabbix.<tool>` として分類されます。

## 注意事項

Codex セッションのタイムスタンプはスパン属性（`codex.timestamp`、`codex.started_at`、`codex.ended_at`）として保持されます。MLflow スパン自体のタイミングはインポート実行時刻を反映します（手動トレーシング API がライブスパンを生成するため）。
