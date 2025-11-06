# kabupilot-3 バックエンド仕様

## 概要

本リポジトリは「AIエージェントによる自動株ポートフォリオ運用」システムの Python 製バックエンド実装を提供する。仕様書として本ファイルを保守し、以下の構成要素を対象とする。

- 週次および日次の運用フロー
- 各エージェントの入出力形式（JSON）
- 依存するサービス／ツール群の責務
- 知識ベースおよびポートフォリオ状態の管理

## アーキテクチャ

```
backend/
  kabupilot_backend/
    agents/
    core/
    services/
    tools/
    workflow.py
    main.py
```

- `core/`：ドメイン共通のデータクラスと基底エージェント実装を提供。
- `agents/`：Planner / PortfolioUpdater / Explorer / ResearchLeader / Researcher / Dicider / Checker を実装。
- `services/`：ポートフォリオ状態や資本情報へのアクセサを提供。
- `tools/`：知識ベースと外部検索ツール（スタブ）を提供。
- `workflow.py`：依存オブジェクトを束ね、週次・日次フロー API を公開。
- `main.py`：CLI デモ用エントリポイント。

## エージェント仕様

### 共通

- `BaseAgent` により活動ログ（`ActivityRecord`）を管理。`run` 実行毎に `activity` をリセットし、出力 JSON に `summary`（`AgentSummary`）と `activity` を含める。
- 入出力は Python の辞書型として扱い、外部公開時には JSON としてシリアライズする。

### Planner

- 入力：なし
- 出力：`weekly_goal`（`WeeklyGoal` → `headline` / `details` / `daily_goals`）、活動記録
- `CapitalService` と `PortfolioRepository` から現状を取得し、知識ベース参照後に週次目標と営業日ごとの `DailyGoal` を生成。

### PortfolioUpdater

- 入力：`DailyGoal`
- 出力：日次サマリ、探索／調査／意思決定各エージェントの活動ログ、実行済みトレードログ
- Explorer → ResearchLeader → Dicider の順で連携し、`Decision` を適用して `PortfolioRepository` を更新。
- トレード適用時は `buy` / `sell` アクションとして `ActivityRecord` に記録。

### Explorer

- 入力：`PortfolioState`
- 出力：候補銘柄リスト、活動記録
- 知識ベース、既存ウォッチリスト、外部検索（スタブ）を利用して銘柄候補を抽出。

### ResearchLeader / Researcher

- ResearchLeader は候補銘柄リストを受け取り、各銘柄について Researcher を起動。
- Researcher は外部検索／Grok（スタブ）を用いた定性的スコアリングを行い、0〜1 に正規化した `ResearchScore` を返す。

### Dicider

- 入力：`ResearchScore` リスト、`PortfolioState`
- 出力：保有・ウォッチ変更案（`Decision`）、活動記録
- 知識ベース・資金情報を参照し、スコアに応じた買付／売却案を生成。

### Checker

- 入力：活動記録、週次目標
- 出力：日次サマリ、知識ベース更新
- 活動記録と最新ポートフォリオ・資本情報から振り返りを行い、`KnowledgeEntry` を追加。

## データモデル

- `PortfolioState`：`cash` / `positions` / `watchlist`
- `Position`：`symbol` / `quantity` / `average_price`
- `WatchItem`：`symbol` / `rationale`
- `DailyGoal` / `WeeklyGoal`：日次・週次目標
- `ResearchScore`：`symbol` / `score` / `rationale`
- `Decision`：`action` / `symbol` / `quantity` / `price`
- `ActivityRecord`：`agent` / `action` / `timestamp` / `details` / `metadata`

## 依存サービス

- `PortfolioRepository`：現金・ポジション・ウォッチリストを保持するインメモリ実装。
- `CapitalService`：保有株価の仮定平均価格を用いて総資産・可投資キャッシュを算出。
- `KnowledgeBase`：`KnowledgeEntry` のリストを管理し、検索・最新取得・追加を提供。
- `InternetSearchTool` / `GrokTool`：ネット検索・SNS 調査のスタブ実装。

## ワークフロー API

- `PortfolioAutomationSystem.plan_week()`：Planner を実行し週次計画を返却。
- `PortfolioAutomationSystem.run_trading_day(daily_goal_payload)`：日次目標を受け取り PortfolioUpdater を実行。
- `PortfolioAutomationSystem.review_day(activity_log, weekly_goal_payload)`：Checker による振り返りを実施。

## 実行方法

```bash
python -m backend.kabupilot_backend.main
```

上記コマンドは週次計画→初日運用→日次振り返りまでを JSON として標準出力するデモを実行する。
