# mcp-pagerduty-kamiyama

PagerDuty REST API を利用した MCP（Model Context Protocol）サーバーです。
Python の FastMCP モジュールを使用し、Streamable HTTP トランスポート（`/mcp`）でポート `8007` で待ち受けます。

最近のインシデント一覧やアサイン状況を確認できます。
ユーザーのメールアドレスや電話番号などの個人情報は取得しません（`assignee` の `id` と表示名のみ返却）。

## 提供するツール

| ツール | 説明 |
|--------|------|
| `list_recent_incidents` | 最近のインシデント一覧（status・days・limit 指定可） |
| `get_incident` | インシデント詳細取得 |
| `get_incident_notes` | インシデントのノート（コメント）一覧 |
| `get_incident_log_entries` | 状態変化・通知の履歴ログ |
| `list_services` | サービス一覧 |
| `list_teams` | チーム一覧 |
| `list_escalation_policies` | エスカレーションポリシー一覧 |

## セットアップ

### 1. リポジトリを取得

```bash
git pull
# または初回なら
git clone <リポジトリURL>
cd mcp-pagerduty-kamiyama
```

### 2. APIキーを設定

`.env` は `.gitignore` 対象のため、`.env.example` をコピーして自分の PagerDuty API キーを記入します。

```bash
cp .env.example .env
```

`.env` の中身を編集：

```
PAGERDUTY_API_KEY=実際のAPIキー
MLFLOW_TRACKING_URI=http://172.16.11.7:5000
```

> APIキーは PagerDuty の管理画面 → **Integrations → API Access Keys** から発行できます（Read-only 推奨）。

## MLflow トレース

`setup_mlflow()` が起動時に `MLFLOW_TRACKING_URI` 環境変数を読み込み、MLflow を初期化します。
各ツール呼び出しは `@mcp_trace` により1呼び出し1トレースとして記録され、PagerDuty API への
HTTP 呼び出しは `mlflow_span` で子スパンとして記録されます（`pagerduty.list_incidents` など）。

トレースの送信先となる MLflow サーバーのアドレスは `.env` の `MLFLOW_TRACKING_URI` で指定してください
（デプロイ先サーバーには `mlflow_codex` モジュールがインストール済みです）。

## 起動方法

### Docker で起動する場合（推奨）

```bash
docker compose up --build
```

- `Dockerfile` を元にイメージをビルド（uv で依存関係をインストール）
- `.env` を読み込んでコンテナを起動
- ポート `8007` をホストにマッピング

バックグラウンド起動:

```bash
docker compose up --build -d
```

停止:

```bash
docker compose down
```

イメージのビルド・起動を個別に行う場合:

```bash
docker build -t mcp-pagerduty-kamiyama .
docker run --rm -p 8007:8007 --env-file .env mcp-pagerduty-kamiyama
```

### Docker を使わずローカル(uv)で起動する場合

```bash
uv sync          # .venv作成＋依存関係インストール（uv.lock に基づく）
uv run python server.py
```

## 動作確認

サーバーが起動すると Streamable HTTP エンドポイントが立ち上がります。

```
http://localhost:8007/mcp
```

MCP クライアント（Claude Desktop など）からこの URL を Streamable HTTP サーバーとして登録すれば、`list_recent_incidents` などのツールが利用できます。
