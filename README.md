# Daily arXiv Digest

毎朝 arXiv の新着論文から、研究グループの関心に合う論文を自動選別し、Slack チャンネルに投稿するシステム。論文の選別には研究グループ固有の判断が必要であり、Claude（LLM）による選別を用いる。選別基準は `criteria.md` に定義されており、グループごとにカスタマイズできる。

## アーキテクチャ

```
GitHub Actions (cron: 毎日 03:00 UTC / 12:00 JST / 11:00 HKT)
  └─ python fetch_arxiv.py → data/latest.json に commit & push

Claude Code Scheduled Task (月〜金 03:10 UTC / 12:10 JST / 11:10 HKT)
  ├─ リポジトリ clone → data/latest.json を読む
  ├─ Claude が CLAUDE.md + criteria.md に従い論文を選別
  └─ output/result.md に書き出し → main に commit & push

GitHub Actions (main push トリガー)
  └─ output/result.md の変更を検知 → Slack Incoming Webhook で #share-paper に投稿
```

- **fetch-arxiv** ワークフロー（12:00 JST / 11:00 HKT）: arXiv API から新着論文を取得し、`data/latest.json` に保存・commit
- **Scheduled Task**（12:10 JST / 11:10 HKT）: JSON を読み込み、`criteria.md` の基準で論文を選出し、`output/result.md` を main に push
- **post-slack** ワークフロー（main push トリガー）: `output/result.md` の変更を検知し、Slack に投稿

この3段階分離は、Claude の計算環境にある egress proxy が `export.arxiv.org` をブロックし、また Slack Connector が不安定なための設計。

## 前提条件

- **Claude Pro 以上のプラン**（Pro / Max / Team / Enterprise）が必要。Free プランでは Scheduled Task を利用できない。（2026年4月時点）

## セットアップ手順

### 1. リポジトリの作成

1. このリポジトリページ右上の **"Fork"** ボタンから自分のアカウントにコピーを作る
2. `criteria.md` を開き、選別基準を自分のグループの研究関心に合わせて書き換える
3. `config.yml` の `categories` を対象の [arXiv カテゴリ](https://arxiv.org/category_taxonomy)に変更する
4. 実行時間を変更したい場合は `config.yml` の `schedule` セクションを参照し、記載された3箇所を更新する

### 2. Slack Incoming Webhook の設定

1. [Slack API: Your Apps](https://api.slack.com/apps) を開き、**"Create New App"** → **"From scratch"** で新しいアプリを作成する
2. 左メニューの **"Incoming Webhooks"** → トグルを **On** にする
3. ページ下部の **"Add New Webhook to Workspace"** をクリックし、投稿先チャンネルを選択して許可する
4. 生成された Webhook URL（`https://hooks.slack.com/services/...`）をコピーする
5. GitHub リポジトリの Settings → Secrets and variables → Actions → **"New repository secret"** で、名前を `SLACK_WEBHOOK_URL`、値にコピーした URL を設定する

### 3. Claude Code Scheduled Task の作成

1. [claude.ai/code/scheduled](https://claude.ai/code/scheduled) にアクセス
2. 「New Scheduled Task」を作成
3. 「Repository」欄で Fork した自分のリポジトリ（`<ユーザ名>/daily-arxiv`）を選択する
4. スケジュールを **Weekdays 12:10 JST**（= 03:10 UTC / 11:10 HKT）に設定
5. **Allow unrestricted branch pushes** を有効にする（main への push に必要）
6. プロンプトに `Read CLAUDE.md and follow the instructions.` と入力する

以上で翌営業日から自動で動き始める。手動で動作確認したい場合は、GitHub Actions の "Fetch arXiv papers" を "Run workflow" で実行し、続けて Scheduled Task を手動トリガーすればよい。

## 既知の制限事項

- **egress proxy**: Claude の計算環境から `export.arxiv.org` に直接アクセスできない。そのため GitHub Actions で事前に論文を取得する2段階アーキテクチャを採用している。
- **arXiv API 上限**: 1クエリあたり最大50件。新着が50件を超えるカテゴリでは一部の論文を取りこぼす可能性がある。取りこぼしが発生した場合は Slack 投稿に注記が付く。
- **Slack Connector 不安定**: Claude Code の Slack Connector が不安定なため（[#43397](https://github.com/anthropics/claude-code/issues/43397)）、GitHub Actions + Incoming Webhook 経由で投稿する設計を採用している。
- **submittedDate ベースの検索**: arXiv の投稿締め切り（ET 14:00）と日付境界のずれにより、少数の論文が前後の日に紛れ込むことがある。実用上の影響は小さい。
