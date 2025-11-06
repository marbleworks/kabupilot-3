# kabupilot-3

AIエージェント自動株ポートフォリオ運用

## セットアップ

Python 3.11 以上を推奨します。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # まだ requirements は不要ですが仮の手順です
```

## CLI での動作確認

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
