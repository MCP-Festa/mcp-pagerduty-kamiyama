# mlflow-codex（MCP Festa 向け）

Codex CLI のセッション JSONL ファイルを MLflow トレースとして記録するツールです。

セッションごとに1つの MLflow トレースを作成します。

> **MCP Festa では AI エージェントとして Codex のみ利用可能です。**

---

## Codex のインストール

Node.js（v22 以上）が必要です。まず Node.js をインストールしてから Codex を入れてください。

**Mac:**
```bash
brew install codex
```

> codex-cli 0.135.0 で動作確認済みです。

**Linux/WSL:**
```bash
# Node.js（v22 以上）が必要です
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
nvm install 22

npm install -g @openai/codex
```

インストール後、動作確認：

```bash
codex --version
```

---

## セットアップ

> **動作環境**: Mac・Linux・WSL では正しく動作するはずです。Windows（WSL なし）では正しく動作しない可能性があります。

### 1. リポジトリをクローン

```bash
git clone https://github.com/MCP-Festa/mlflow-codex.git
cd mlflow-codex
```

### 2. セットアップ

```bash
make setup
```

`@mlflow/codex` のグローバルインストール・パッチ適用・Python 依存関係の同期を一括で実行します。

完了後、以下を設定してください。

### 3. Codex の設定 (`~/.codex/config.toml`)

`config.toml.example` を参考に `~/.codex/config.toml` を作成してください。`<your-mcp-port>`スプレッドシートで予約したポート番号を入力してください 

```toml
model = "gpt-5.2"
model_provider = "azure"
model_reasoning_effort = "medium"

notify = ["mlflow-codex", "notify-hook"]

[model_providers.azure]
name = "Azure OpenAI"
base_url = "https://mcpfes-shownet2026.openai.azure.com/openai/v1"
env_key = "AZURE_OPENAI_API_KEY"
wire_api = "responses"

[notice.model_migrations]
"gpt-5.2" = "gpt-5.4"

[mcp_servers.zabbix]
url = "http://172.16.11.9:<your-mcp-port>/mcp"
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 60
```

### 4. Azure OpenAI API キーの設定

API キーは Webex DM でお渡しします。コードには直接書き込まず、環境変数として設定してください。

```bash
export AZURE_OPENAI_API_KEY=<受け取ったAPIキー>
```

`config.toml` の `env_key = "AZURE_OPENAI_API_KEY"` により、Codex が自動でこの環境変数を読み込みます。

### 5. MLflow トラッキング URI の設定

`~/.codex/mlflow-tracing.json` を新規作成し、以下の内容を記述してください。

```json
{
  "trackingUri": "http://172.16.11.7:5000",
  "experimentId": "0"
}
```

---

## MCP サーバーへの MLflow トレース追加ルール

MLflow で MCP サーバーのツール呼び出しを分析するには、MCPサーバーのコードに以下の変更が必要です。

### 1. 起動時に `setup_mlflow()` を呼ぶ

```python
from mlflow_codex.mcp import setup_mlflow, mcp_trace, mlflow_span

setup_mlflow()  # MLFLOW_TRACKING_URI 環境変数を読んで MLflow を初期化
```

`MLFLOW_TRACKING_URI` 環境変数に MLflow サーバーのアドレスを設定してください。

```bash
export MLFLOW_TRACKING_URI=http://172.16.11.7:5000
```

### 2. 各 MCP ツールに `@mcp_trace` を付ける

ツール関数の既存デコレータはそのままに、`@mcp_trace` を追加します。

```python
@mcp.tool()
@mcp_trace          # ← 追加：ツール呼び出し1回につき1トレースを記録
@_trace()           # 既存のロガーはそのまま
async def my_tool(...): ...
```

### 3. HTTP/RPC 呼び出しを `mlflow_span` で囲む（推奨）

ツール内部の外部サービス呼び出しを子スパンとして記録することで、詳細な分析が可能になります。

```python
async with mlflow_span(f"zabbix.{method}") as span:
    if span:
        span.set_attribute("zabbix.result_count", len(result))
    result = await rpc(...)
```

---

## Appendix: MCP サーバーへの組み込み方（サンプルコード）

実際にどう書けばよいか、シンプルな MCP サーバーを例に説明します。

### 最小構成の例

```python
from mcp.server.fastmcp import FastMCP
from mlflow_codex.mcp import setup_mlflow, mcp_trace

# MLflow の初期化（起動時に1回だけ呼ぶ）
setup_mlflow()

mcp = FastMCP("my-server")

@mcp.tool()
@mcp_trace  # ← これを付けるだけでツール呼び出しが MLflow に記録される
async def hello(name: str) -> str:
    return f"Hello, {name}!"
```

これだけで、`hello` ツールが呼ばれるたびに MLflow にトレースが記録されます。

### 外部 API 呼び出しを含む例

ツール内で HTTP リクエストなど外部サービスを呼ぶ場合、`mlflow_span` で囲むと「どの処理に時間がかかったか」を MLflow UI で確認できます。

```python
import httpx
from mcp.server.fastmcp import FastMCP
from mlflow_codex.mcp import setup_mlflow, mcp_trace, mlflow_span

setup_mlflow()
mcp = FastMCP("my-server")

@mcp.tool()
@mcp_trace
async def get_data(host: str) -> dict:
    # mlflow_span で囲んだ処理が子スパンとして記録される
    async with mlflow_span("api.get_data") as span:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://{host}/api/data")
            result = response.json()
        if span:
            span.set_attribute("api.result_count", len(result))
    return result
```

MLflow UI でのトレース表示イメージ：

```
トレース: get_data                （例: 320ms）
  └─ 子スパン: api.get_data       （例: 290ms）
```

### `MLFLOW_TRACKING_URI` の設定

サーバー起動前に環境変数を設定してください。

```bash
export MLFLOW_TRACKING_URI=http://172.16.11.7:5000
python my_server.py
```
