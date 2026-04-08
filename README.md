# Daily arXiv Digest — Watanabe Group @ HKUST

毎朝 arXiv の新着論文（cond-mat.str-el, cond-mat.stat-mech）から、渡辺悠樹グループの研究関心に合う論文を自動選別し、Slack の #share-paper チャンネルに投稿するシステム。論文の選別には「模型の詳細を超えた一般的知見を与えているか」という判断が必要であり、Claude（LLM）による3段階フィルタリングを用いる。

## アーキテクチャ

```
GitHub Actions (cron: 月〜金 00:50 UTC / 09:50 JST)
  └─ python fetch_arxiv.py → data/latest.json に commit & push

Claude Code Scheduled Task (月〜金 01:00 UTC / 10:00 JST)
  ├─ リポジトリ clone → data/latest.json を読む
  ├─ Claude が CLAUDE.md に従い3段階フィルタリング
  └─ output/result.md に書き出し → main に commit & push

GitHub Actions (main push トリガー)
  └─ output/result.md の変更を検知 → Slack Incoming Webhook で #share-paper に投稿
```

- **fetch-arxiv** ワークフロー（09:50 JST）: arXiv API から新着論文を取得し、`data/latest.json` に保存・commit
- **Scheduled Task**（10:00 JST）: JSON を読み込み、3段階フィルタリングで5件を選出し、`output/result.md` を main に push
- **post-slack** ワークフロー（main push トリガー）: `output/result.md` の変更を検知し、Slack に投稿

この3段階分離は、Claude の計算環境にある egress proxy が `export.arxiv.org` をブロックし、また Slack Connector が不安定なための設計。

## セットアップ手順

### 1. リポジトリの作成

このリポジトリを private で GitHub に作成する。

### 2. GitHub Actions の動作確認

Actions タブ → "Fetch arXiv papers" → "Run workflow" で手動実行し、`data/latest.json` が生成・commit されることを確認する。

### 3. Slack Incoming Webhook の設定

1. Slack App で Incoming Webhook を作成し、`#share-paper` チャンネルに紐付ける
2. GitHub リポジトリの Settings → Secrets and variables → Actions で `SLACK_WEBHOOK_URL` を設定

### 4. Claude Code Scheduled Task の作成

1. [claude.ai/code/scheduled](https://claude.ai/code/scheduled) にアクセス
2. 「New Scheduled Task」を作成
3. リポジトリに `daily-arxiv` を接続
4. スケジュールを **Weekdays 10:00 JST**（= 01:00 UTC）に設定
5. プロンプトは空でよい（`CLAUDE.md` が自動的に読み込まれる）

### 5. 手動テスト

1. GitHub Actions の fetch-arxiv を手動実行して `data/latest.json` を生成
2. Scheduled Task を手動トリガーして、`output/result.md` が main に push されることを確認
3. post-slack ワークフローが自動発火し、Slack に投稿されることを確認

## 既知の制限事項

- **egress proxy**: Claude の計算環境から `export.arxiv.org` に直接アクセスできない。そのため GitHub Actions で事前に論文を取得する2段階アーキテクチャを採用している。
- **arXiv API 上限**: 1クエリあたり最大50件。新着が50件を超えるカテゴリでは一部の論文を取りこぼす可能性がある。取りこぼしが発生した場合は Slack 投稿に注記が付く。
- **Slack Connector 不安定**: Claude Code Cloud の Slack Connector が不安定なため（[#43397](https://github.com/anthropics/claude-code/issues/43397)）、GitHub Actions + Incoming Webhook 経由で投稿する設計を採用している。
- **submittedDate ベースの検索**: arXiv の投稿締め切り（ET 14:00）と日付境界のずれにより、少数の論文が前後の日に紛れ込むことがある。実用上の影響は小さい。
