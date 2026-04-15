# Daily arXiv Digest

毎朝 arXiv の新着論文から、研究グループの関心に合う論文を自動選別し、Slack チャンネルに投稿するシステム。論文の選別には研究グループ固有の判断が必要であり、Claude Code の Scheduled Task による LLM 選別を用いる。選別基準は `criteria.md` に定義されており、グループごとにカスタマイズできる。

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

この分離は、Claude の計算環境にある egress proxy が `export.arxiv.org` をブロックし、また Slack Connector が不安定なための設計。

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

1. **トリガー**: Scheduled Task が `data/trigger.txt` を main に push する
2. **論文取得**: GitHub Actions が `fetch_arxiv.py` を実行し、arXiv API から論文を取得して `data/latest.json` に保存・push する
3. **論文選別**: Scheduled Task が `data/latest.json` を pull で取得し、`criteria.md` の基準に従って5件程度を選出する
4. **Slack 投稿**: 選別結果を `output/result.md` に書き出して push すると、GitHub Actions が Slack Webhook 経由で各論文を1メッセージずつ投稿する

## 前提条件

- **Claude Pro 以上のプラン**（Pro / Max / Team / Enterprise）が必要。Free プランでは Scheduled Task を利用できない。（2026年4月時点）

## セットアップ手順

### 1. リポジトリの作成

1. このリポジトリページ右上の **"Fork"** ボタンから自分のアカウントにコピーを作る
2. `criteria.md` を開き、選別基準を自分のグループの研究関心に合わせて書き換える
3. `config.yml` の `categories` を対象の [arXiv カテゴリ](https://arxiv.org/category_taxonomy)に変更する

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
4. スケジュールを **Everyday** で好みの配信時刻に設定（実行時刻は論文の取得範囲に影響しない。詳細は「時刻と日付の扱い」を参照）
5. **Allow unrestricted branch pushes** を有効にする（main への push に必要）
6. プロンプトに `Read CLAUDE.md and follow the instructions.` と入力する

以上で翌日から自動で動き始める。手動で動作確認したい場合は、Scheduled Task を手動トリガーすればよい（fetch も自動で起動される）。

## 時刻と日付の扱い

### arXiv の公開スケジュール

arXiv は米国東部時間（ET）を基準に運用されている。

- **投稿締切**: 毎日 14:00 ET（月〜金）
- **新着公開**: 毎日 ~20:00 ET（月〜金）。土日は公開なし
- 例：木曜 14:00 ET までの投稿 → 木曜 20:00 ET に公開

### なぜ2日遅れで取得するのか

`fetch_arxiv.py` は arXiv API の `submittedDate`（投稿日時）で論文を検索する。ただし arXiv の「新着リスト」は公開日でグループ化されており、`submittedDate` とは1日ずれることがある：

- 水曜 15:00 ET に投稿 → `submittedDate` = 水曜 → **木曜の新着**として公開
- 木曜 10:00 ET に投稿 → `submittedDate` = 木曜 → **木曜の新着**として公開

このずれを吸収するため、取得対象の終了日を「2日前」に設定している。さらに、前回の取得範囲の最終日を再クエリ（1日重複）し、前回と比べて新しい論文がない場合は取得範囲を進めない。これにより、休日・祝日を挟んで API 反映が遅れた論文も確実に取得できる。

### Scheduled Task の実行時刻

Scheduled Task の実行時刻は論文の取得範囲に影響しない（2日前の論文は時刻によらず確実にアクセス可能）。配信時刻の好みに合わせて自由に設定してよい。

## 既知の制限事項

- **egress proxy**: Claude の計算環境から `export.arxiv.org` に直接アクセスできない。そのため GitHub Actions で事前に論文を取得する2段階アーキテクチャを採用している。
- **arXiv API 上限**: 1クエリあたり最大50件。新着が50件を超えるカテゴリでは一部の論文を取りこぼす可能性がある。取りこぼしが発生した場合は Slack 投稿に注記が付く。
- **Slack Connector 不安定**: Claude Code の Slack Connector が不安定なため（[#43397](https://github.com/anthropics/claude-code/issues/43397)）、GitHub Actions + Incoming Webhook 経由で投稿する設計を採用している。
