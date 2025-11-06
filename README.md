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

3. 1 日のポートフォリオ更新フローを実行します。

   ```bash
   python -m kabupilot.cli run-daily
   ```

4. 現在のポートフォリオ状況を確認します。

   ```bash
   python -m kabupilot.cli show-portfolio
   ```

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
