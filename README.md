# kabupilot-3

AIエージェント自動株ポートフォリオ運用

## セットアップ

Python 3.11 以上を推奨します。

```bash
python -m venv .venv
source .venv/bin/activate
cd backend
pip install -r requirements.txt  # まだ requirements は不要ですが仮の手順です
```

`requirements.txt` には yfinance のほか OpenAI / xAI API を呼び出すためのクライアントライブラリ（`openai`、`requests`）が含まれています。
実際に LLM を利用する場合は以下の環境変数を設定してください。

| 変数名 | 説明 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI (GPT) の API キー。|
| `XAI_API_KEY` | xAI Grok API の API キー。|
| `XAI_BASE_URL` | 任意。自前のプロキシなど別エンドポイントを利用する場合に上書きします。|

いずれも `export OPENAI_API_KEY=...` のようにシェル環境で設定してから CLI を実行してください。

## CLI での動作確認

以下のコマンドは `backend` ディレクトリ内で実行してください。

1. SQLite データベースを初期化します。

   ```bash
   python -m kabupilot.cli init-db --force
   ```

2. 週次プランナーを実行し、目標を記録します。

   ```bash
   python -m kabupilot.cli run-planner
   ```

3. 1 日のポートフォリオ更新フローを実行します（結果をメモ更新用に保存することも可能です）。

   ```bash
   python -m kabupilot.cli run-daily --result-path daily_result.json
   ```

4. Checker エージェントで共有メモを更新します（`run-daily` で保存した結果を読み込みます）。

   ```bash
   python -m kabupilot.cli update-memo --result-path daily_result.json
   ```

5. 現在のポートフォリオ状況を確認します。

   ```bash
   python -m kabupilot.cli show-portfolio
   ```

### ナレッジベースについて

* ナレッジベースはエージェント共有のメモとして `kabupilot.db` の `knowledge_documents` テーブルに保存されます。
* `init-db` 実行時に市場ごとのテンプレートメモが作成され、`update-memo` コマンドで Checker が各エージェントの活動サマリ・反省点・要求を反映します（`run-daily` で出力した JSON を渡すと詳細な日次結果を組み込めます）。
* Explorer/Researcher などのエージェントはメモに記載された銘柄や要望を参照し、次回の動作に反映します。

### 市場設定の切り替え

設定値は SQLite データベースに保存されます。デフォルトは日本株（`jp`）です。

米国株へ切り替える場合は以下を実行してください（必要に応じてウォッチリストも再構築されます）。

```bash
python -m kabupilot.cli set-market us --refresh-watchlist
```

再度日本株へ戻す場合：

```bash
python -m kabupilot.cli set-market jp --refresh-watchlist
```

ウォッチリストの初期値は市場ごとの定義済みセットから再構築され、共有メモは市場設定に応じた同一ドキュメントを参照します。
