# Daily arXiv Digest — Watanabe Group @ HKUST

毎朝 arXiv の新着論文（cond-mat.str-el, cond-mat.stat-mech）から、渡辺悠樹グループの研究関心に合う論文を自動選別し、Slack の #share-paper チャンネルに投稿するシステム。論文の選別には「模型の詳細を超えた一般的知見を与えているか」という判断が必要であり、Claude（LLM）による3段階フィルタリングを用いる。

## アーキテクチャ

```
GitHub Actions (cron: 月〜金)
  └─ python fetch_arxiv.py → data/latest.json に commit & push

Claude Code Scheduled Task (月〜金、GitHub Actions の約10分後)
  ├─ リポジトリ clone → data/latest.json を読む
  ├─ Claude が CLAUDE.md に従い3段階フィルタリング
  └─ Slack Connector → #share-paper
      （失敗時は output/ にファイル出力 + claude/ ブランチに push）
```

- **GitHub Actions**（00:50 UTC / 09:50 JST）: arXiv API から新着論文を取得し、`data/latest.json` に保存・commit
- **Claude Code Scheduled Task**（10:00 JST）: JSON を読み込み、3段階フィルタリングで5件を選出し、Slack に投稿

この2段階分離は、Claude の計算環境にある egress proxy が `export.arxiv.org` をブロックするための設計。

## セットアップ手順

### 1. リポジトリの作成

このリポジトリを private で GitHub に作成する。

### 2. GitHub Actions の動作確認

Actions タブ → "Fetch arXiv papers" → "Run workflow" で手動実行し、`data/latest.json` が生成・commit されることを確認する。

### 3. Claude Code Scheduled Task の作成

1. [claude.ai/code/scheduled](https://claude.ai/code/scheduled) にアクセス
2. 「New Scheduled Task」を作成
3. リポジトリに `daily-arxiv` を接続
4. Connectors で **Slack** を有効化（#share-paper チャンネルへのアクセスが必要）
5. スケジュールを **Weekdays 10:00 JST**（= 01:00 UTC）に設定
6. プロンプトは空でよい（`CLAUDE.md` が自動的に読み込まれる）

### 4. 手動テスト

1. GitHub Actions を手動実行して `data/latest.json` を生成
2. Scheduled Task を手動トリガーして、Slack に投稿されることを確認

## 既知の制限事項

- **egress proxy**: Claude の計算環境から `export.arxiv.org` に直接アクセスできない。そのため GitHub Actions で事前に論文を取得する2段階アーキテクチャを採用している。
- **arXiv API 上限**: 1クエリあたり最大50件。新着が50件を超えるカテゴリでは一部の論文を取りこぼす可能性がある。取りこぼしが発生した場合は Slack 投稿に注記が付く。
- **Connector 初期化バグ**: Scheduled Task で MCP Connector が初期化されない既知のバグがある（[#43397](https://github.com/anthropics/claude-code/issues/43397), [#35899](https://github.com/anthropics/claude-code/issues/35899), [#36327](https://github.com/anthropics/claude-code/issues/36327)）。Slack Connector は標準搭載で比較的安定しているが、問題が発生した場合はフォールバック（`output/result.md` + `claude/` ブランチ push）が機能する。
- **submittedDate ベースの検索**: arXiv の投稿締め切り（ET 14:00）と日付境界のずれにより、少数の論文が前後の日に紛れ込むことがある。実用上の影響は小さい。
