# Daily arXiv Digest — Routine / Slack Connector 並走テスト版

**目的**: 安定版（`CLAUDE.md`、GitHub Actions + Incoming Webhook 経由）と並走させて、Slack connector を使った新フローの信頼性を検証する。

**原則**:
- 共有 state（`data/trigger.txt`, `data/latest.json`, `data/last_processed.json`, `output/result.md`）は**一切書き換えない**
- `fetch-arxiv` ワークフローを**トリガーしない**（安定版が既に今日分を取得している前提で動く）
- 投稿先は `config.yml` の `slack_channel_test` で指定された**テスト専用チャンネル**（本番チャンネルには投稿しない）
- commit / push を**しない**

---

## Step 1: 最新データの読み込み

1. main ブランチを pull する: `git checkout main && git pull origin main`
2. `data/latest.json` を読み込む
   - ファイルが存在しない、または `papers` が空配列の場合は何もせず終了
   - 安定版が同日にまだ走っていない場合、`latest.json` は前日以前のものになる。それでも構わずそのまま処理する（本テストはコネクタ動作確認が目的）

### JSON 構造

`CLAUDE.md` の「Step 1」に記載のものと同じ。

### 取りこぼし検知

`total_results` のいずれかが 50 を超えている場合、Step 3 の投稿末尾に以下の注記メッセージを追加する（1 件の独立したメッセージとして）:

「⚠ {カテゴリ名} の新着が {total_results} 件あり、取得上限（50件）を超えたため一部の論文を取得できていません」

---

## Step 2: 論文の選別

`criteria.md` を読み込み、そこに定義された基準とプロセスに従って `latest.json` の**全論文**から選別する。

**重複防止チェックは行わない**。`data/last_processed.json` は読まず、書かない。安定版と同じ論文が並走で投稿されても問題ない（別チャンネル）。

---

## Step 3: Slack connector 投稿

`config.yml` の `slack_channel_test` を読み、そこに指定された宛先に選出した論文を **1 件ずつ別メッセージ** として Slack connector で投稿する。

### 宛先解決

`slack_channel_test` は自然言語で書かれうる（例: `"自分への DM"`, `"#arxiv-digest-test"`, `"XXX ワークスペースの #channel"` など）。Slack connector の検索系ツール（`slack_search_users`, `slack_search_channels` など利用可能なもの）で実際の ID を解決してから投稿すること。

**複数ワークスペース対策**: Slack connector に複数のワークスペースが接続されている可能性がある。`slack_channel_test` にワークスペース名の明示がなく、候補が複数見つかる場合は、**投稿せず失敗扱いで終了する**（ユーザーにログで知らせる。誤爆を避けるため曖昧なまま投稿しない）。ワークスペース名が明示されている場合はそれと一致するものを選ぶ。

### フォーマット（mrkdwn）

```
*{タイトル}*
{著者カンマ区切り}
https://arxiv.org/abs/{arXiv_ID}
```

- タイトルは `*...*` で太字
- 著者はカンマ区切り
- リンクは URL のみ（Slack が自動アンフル展開する）
- スコア、要約、カテゴリ等は含めない
- 投稿順は Step 2 の選出順
- メッセージの順序を保つため、投稿ごとに 1〜2 秒の間隔を入れる

取りこぼし注記がある場合は全論文の投稿後に追加で 1 メッセージ投稿する。

---

## Step 4: 終了

- `output/result.md` を**更新しない**
- `data/last_processed.json` を**更新しない**
- commit / push を**一切しない**
- 以上で終了

---

## 観察ポイント（テスト期間中）

- Slack connector 投稿が 5/5 件成功するか（部分失敗・欠落・重複・順序崩れがないか）
- メッセージフォーマット（太字、リンク、改行）が Webhook 版と同等の見た目になるか
- 実行時間が安定版と比べて許容範囲か
- エラー時の挙動（connector 認証切れ、チャンネル不在、等）

テスト期間後、安定版との置き換えを判断する。置き換え時は `CLAUDE.md` 本体を更新し、本ファイルと `post-slack.yml` を削除する。
