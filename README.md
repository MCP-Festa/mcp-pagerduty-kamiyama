# mcp-pagerduty-kamiyama

PagerDuty REST API を利用した MCP（Model Context Protocol）サーバーです。
Python の FastMCP モジュールを使用し、SSE トランスポートでポート `8007` で待ち受けます。

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
```

> APIキーは PagerDuty の管理画面 → **Integrations → API Access Keys** から発行できます（Read-only 推奨）。

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

サーバーが起動すると SSE エンドポイントが立ち上がります。

```
http://localhost:8007/sse
```

MCP クライアント（Claude Desktop など）からこの URL を SSE サーバーとして登録すれば、`list_recent_incidents` などのツールが利用できます。
