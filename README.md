# kabupilot-3

AIエージェント自動株ポートフォリオ運用のバックエンド実装。

## セットアップ

Python 3.10 以上を想定しています。必要に応じて仮想環境を作成してください。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 実行

デモとして週次計画 → 初日運用 → 日次振り返りまでを一括実行する CLI を同梱しています。

```bash
python -m backend.kabupilot_backend.main
```

標準出力に各エージェントの JSON 結果が表示されます。

## プロジェクト構成

- `backend/kabupilot_backend/`：Python パッケージ本体
  - `core/`：ドメインモデルと基底エージェント
  - `services/`：ポートフォリオ／資金データアクセサ
  - `tools/`：知識ベースと外部調査ツール（スタブ）
  - `agents/`：各エージェントの実装
  - `workflow.py`：全エージェントを束ねるオーケストレータ
  - `main.py`：CLI エントリポイント
- `specification.md`：システム仕様書
- `pyproject.toml`：パッケージ設定
