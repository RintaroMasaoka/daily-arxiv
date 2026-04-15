# Daily arXiv Digest

毎朝 arXiv の新着論文から、研究グループの関心に合う論文を自動選別し、Slack チャンネルに投稿するシステム。論文の選別には研究グループ固有の判断が必要なため、Claude Code の Scheduled Task による LLM 選別を用いる。選別基準は `criteria.md` に定義されており、グループごとにカスタマイズできる。

## アーキテクチャ

```
Claude Code (Scheduled Task)        GitHub Actions              外部サービス
────────────────────────────        ──────────────              ────────────
data/trigger.txt を push ──────→  fetch-arxiv 起動
                                    fetch_arxiv.py ──────────→ arXiv API
                                    data/latest.json を push
data/latest.json を pull ←─────
論文選別 (criteria.md に基づく)
output/result.md を push ─────→  post-slack 起動
                                    result.md をパース ──────→ Slack Webhook
```

Claude の計算環境から `export.arxiv.org` にアクセスできないため、論文取得は GitHub Actions に委譲する設計。Slack への投稿も GitHub Actions + Incoming Webhook 経由で行う（Claude Code の Slack Connector が不安定なため）。

## ファイル構成

```
├── CLAUDE.md                  # Scheduled Task 用の実行手順書
├── criteria.md                # 論文選別基準（グループごとにカスタマイズ）
├── config.yml                 # 取得対象の arXiv カテゴリ
├── fetch_arxiv.py             # arXiv API から論文を取得するスクリプト
├── data/
│   ├── trigger.txt            # fetch-arxiv ワークフローのトリガー
│   ├── latest.json            # 最新の取得結果
│   └── last_processed.json    # 重複投稿防止用の処理済み論文 ID
├── output/
│   └── result.md              # 選別結果（Slack 投稿の元データ）
└── .github/workflows/
    ├── fetch-arxiv.yml        # data/trigger.txt の push で起動
    └── post-slack.yml         # output/result.md の変更で起動
```

## 処理フロー

1. **トリガー**: Scheduled Task が `data/trigger.txt` を push
2. **論文取得**: GitHub Actions が `fetch_arxiv.py` を実行し、arXiv API から論文を取得して `data/latest.json` に保存
3. **論文選別**: Scheduled Task が `data/latest.json` を読み込み、`criteria.md` の基準に従って5件程度を選出
4. **Slack 投稿**: 選別結果を `output/result.md` に書き出して push → GitHub Actions が Slack Webhook で投稿

## 前提条件

- **Claude Pro 以上のプラン**（Pro / Max / Team / Enterprise）— Scheduled Task の利用に必要
- **GitHub リポジトリ** — Actions が有効であること
- **Slack Incoming Webhook URL** — GitHub リポジトリの Secret に `SLACK_WEBHOOK_URL` として設定

## セットアップ手順

### 1. リポジトリの準備

1. このリポジトリを Fork する
2. `criteria.md` を開き、選別基準を自分のグループの研究関心に合わせて書き換える
3. `config.yml` の `categories` を対象の [arXiv カテゴリ](https://arxiv.org/category_taxonomy)に変更する

### 2. Slack Incoming Webhook の設定

1. [Slack API: Your Apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. **Incoming Webhooks** → トグルを On → **Add New Webhook to Workspace** で投稿先チャンネルを選択
3. 生成された Webhook URL をコピー
4. GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で `SLACK_WEBHOOK_URL` を設定

### 3. Scheduled Task の作成

1. [claude.ai/code/scheduled](https://claude.ai/code/scheduled) にアクセス
2. **New Scheduled Task** を作成
3. Fork したリポジトリを選択
4. スケジュールを **Everyday** で好みの時刻に設定
5. **Allow unrestricted branch pushes** を有効にする
6. プロンプト: `Read CLAUDE.md and follow the instructions.`

以上で翌日から自動で動き始める。手動で動作確認したい場合は Scheduled Task を手動トリガーすればよい。

## 時刻と日付の扱い

### arXiv の公開スケジュール

- **投稿締切**: 毎日 14:00 ET（月〜金）
- **新着公開**: 毎日 ~20:00 ET（月〜金）。土日は公開なし

### 2日オフセットと1日重複

`fetch_arxiv.py` は arXiv API の `submittedDate` で論文を検索する。投稿日と公開日が1日ずれることがあるため、取得対象の終了日を「2日前」に設定している。さらに、前回の取得範囲の最終日を再クエリ（1日重複）することで、遅れてインデックスされた論文を確実に取得する。

### Scheduled Task の実行時刻

実行時刻は論文の取得範囲に影響しない（2日前の論文は時刻によらずアクセス可能）。配信時刻の好みに合わせて設定してよい。

## 既知の制限事項

- **arXiv API 上限**: 1クエリあたり最大50件。超過した場合は Slack 投稿に注記が付く
- **egress proxy**: Claude の計算環境から `export.arxiv.org` にアクセスできないため、GitHub Actions 経由で取得する2段階設計
- **Slack Connector**: Claude Code の Slack Connector が不安定なため（[#43397](https://github.com/anthropics/claude-code/issues/43397)）、Incoming Webhook を使用
