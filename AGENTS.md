# Daily arXiv Digest

このタスクは arXiv 新着論文の取得・選別・Slack 投稿を行う。論文取得はまず GitHub Actions に委譲する。Actions の取得が失敗した場合に限り、タスク側の `curl` 経路で復旧を試みる。

---

## Step 0: 論文データの取得

GitHub Actions の `fetch-arxiv` ワークフローをトリガーし、最新の論文データを取得する。

### 手順

1. main ブランチに切り替える: `git checkout main && git pull origin main`
2. トリガーファイルを push する:
   ```
   date -u > data/trigger.txt
   git add data/trigger.txt
   git commit -m "Trigger fetch"
   git push origin main
   ```
3. 以下のシェルスクリプトを **1回の `bash` コマンドとして実行** し、`data/latest.json` が更新されるまで poll する:
   ```bash
   TRIGGER_SHA=$(git rev-parse HEAD)
   OLD=$(cat data/latest.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('fetched_at',''))" 2>/dev/null || echo "")
   for i in $(seq 1 20); do
     sleep 15
     git pull origin main --quiet
     NEW=$(cat data/latest.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('fetched_at',''))" 2>/dev/null || echo "")
     if [ "$NEW" != "$OLD" ] && [ -n "$NEW" ]; then echo "UPDATED"; exit 0; fi
   done
   echo "TIMEOUT trigger_sha=$TRIGGER_SHA"
   exit 1
   ```
   - 結果が `UPDATED` なら Step 1 へ進む
   - 結果が `TIMEOUT`（終了コード1）なら、出力された `trigger_sha` に対応する GitHub Actions の `fetch-arxiv` 実行結果を確認する。実行中なら完了まで待ち、`git pull origin main` して `latest.json` を再確認する。`git show {trigger_sha}:data/latest.json` の `fetched_at` と比較し、更新されていれば Step 1 へ進む。取得ステップが失敗していた場合は、Actions のログから対象カテゴリ・日付、HTTP ステータス、試行回数、記録された応答ヘッダーと本文の抜粋、実行URLを確認し、以下の `curl` 復旧経路を試す。GitHub Actions も既存の Slack Webhook に簡潔な失敗通知を送る。成功していて `latest.json` が更新されなかった場合は、新しい論文がなかったと判断して終了する。いずれの場合も既存の `latest.json` を処理してはならない。
   - 対応する実行は GitHub Actions の `fetch-arxiv` 履歴から `trigger_sha` で特定する。GitHub API を使う場合は `https://api.github.com/repos/RintaroMasaoka/daily-arxiv/actions/workflows/fetch-arxiv.yml/runs?head_sha={trigger_sha}` を参照する。

**重要**: Scheduled Task は `claude/*`、`codex/*` または `Codex/*` ブランチ上で開始されることがあるが、トリガーには main への push が必要なため、最初に main に切り替えること。

### Actions 取得失敗時の `curl` 復旧経路

1. Actions の取得ステップが失敗し、実行が完了したことを確認する。`data/latest.json` の現在の `fetched_at` を記録する。
2. main の作業ツリーで `python3 fetch_arxiv.py --transport curl` を実行する。これは Actions と同じ日付計算・カテゴリ・Atom 検証・重複除去を使い、各 API リクエストのみ `curl` で行う。sandbox の DNS/network 制限で失敗した場合は、同じコマンドを通常の Mac 環境で権限昇格して再実行する（DNS 失敗はコードが長い再試行なしで終了する）。arXiv が HTTP 429 などを返した場合はコード内の再試行に任せる。
3. コマンドが失敗した場合は既存の `latest.json` を処理せず、Actions と `curl` の両方の取得エラーをこのタスクの結果として報告して終了する。成功しても `fetched_at` が変わらなければ、新しい論文がなかったものとして投稿せず終了する。
4. `fetched_at` が変わった場合は `data/latest.json` だけを commit して main に push し、Step 3 の `PUSH_VERIFIED` ゲートで push を確認してから Step 1 に進む。復旧成功時も、Actions の失敗と `curl` による復旧をこのタスクの結果に記す。無関係な作業ツリーの変更は保持する。

**Codex 実行時の注意**: `git pull` / `git push` が sandbox や network 権限で失敗した場合は、同じコマンドを権限昇格して再実行する。`export.arxiv.org` へのタスク側の直接アクセスは、上記の復旧経路に限る。

---

## Step 1: 論文データの読み込み

`data/latest.json` を読み込む（Step 0 で更新済み）。

### JSON の構造

```json
{
  "fetched_at": "2026-04-08T09:00:00+09:00",
  "date_from": "2026-04-07",
  "date_to": "2026-04-07",
  "categories_queried": ["cond-mat.str-el", "cond-mat.stat-mech"],
  "total_results": {"cond-mat.str-el": 35, "cond-mat.stat-mech": 22},
  "papers": [
    {
      "arxiv_id": "2604.12345",
      "title": "...",
      "authors": ["Alice", "Bob"],
      "abstract": "...",
      "categories": ["cond-mat.str-el", "quant-ph"]
    }
  ]
}
```

### 取りこぼし検知

`total_results` を確認する。いずれかのカテゴリで値が **50を超えている** 場合、Slack 投稿の末尾に以下の注記を追加する：

「⚠ {カテゴリ名} の新着が {total_results} 件あり、取得上限（50件）を超えたため一部の論文を取得できていません」

### 重複投稿の防止

`data/last_processed.json` を読み込み、`latest.json` の論文から `seen_ids` に含まれる論文を除外する。除外後に論文が0件になった場合は、何も送信せず終了する。

`data/last_processed.json` の構造：

```json
{
  "processed_at": "2026-04-08T09:05:00+09:00",
  "seen_ids": ["2604.12345", "2604.12346"]
}
```

`seen_ids` は過去に `latest.json` に含まれていた全論文の `arxiv_id` のリスト。選別対象は `seen_ids` に**含まれない**論文のみ。

このファイルが存在しない場合（初回実行時）はチェックをスキップし、全論文を対象とする。
このファイルの更新は Step 3 の公開手順で行う。

### 取得0件の場合

`papers` が空配列の場合は、何も送信せず終了する。

---

## Step 2: 論文の選別

`criteria.md` を読み込み、そこに定義された基準とプロセスに従って論文を選別する。

選別対象の新規論文はあるが、基準に照らして選出論文が0件になった場合も Step 3 へ進む。この場合、`output/result.md` は空にし、`data/last_processed.json` は更新して commit & push する。`post-slack` ワークフローは空の `result.md` からは何も投稿しないため、Slack には送信されない。

---

## Step 3: 結果の書き出しと公開

選出した論文を `output/result.md` に書き出し、main ブランチに push する。
push をトリガーに GitHub Actions が Slack へ投稿するため、このタスクでは Slack に直接送信しない。

### 書き出し形式

選出した全論文を `output/result.md` に以下の形式で書き出す：

```
- *{タイトル1}*
{著者1}
https://arxiv.org/abs/{arXiv_ID_1}

- *{タイトル2}*
{著者2}
https://arxiv.org/abs/{arXiv_ID_2}

...
```

各論文はタイトル（Slack mrkdwn の `*...*` で太字）、著者、リンクを記載し、論文間は空行で区切る。
選出順（Step 2の結果順）に並べる。
それ以外の情報（スコア、要約、カテゴリ等）は含めない。

### 取りこぼし注記

Step 1 で取りこぼしが検出された場合は、論文リストの末尾に注記を追加する。

### 公開手順

1. `output/result.md` を作成（既存ファイルがあれば上書き）
2. `data/last_processed.json` を更新する：現在時刻の `processed_at` と、`seen_ids`（前回の `seen_ids` に今回の `latest.json` の全 `arxiv_id` を追加したもの）を記録する
3. `output/result.md` と `data/last_processed.json` を commit する（Step 0 で main ブランチに切り替え済み）
4. `git push origin main` を実行する。**この push が GitHub Actions の Slack 投稿をトリガーする**。Codex sandbox / network 権限で push が失敗した場合は権限昇格して再実行する
5. **push 検証ゲート**: 以下を **1回の `bash` コマンドとして実行** し、ローカル HEAD が origin/main に到達したことを確認する：
   ```bash
   git fetch origin main --quiet
   LOCAL=$(git rev-parse HEAD)
   REMOTE=$(git rev-parse origin/main)
   if [ "$LOCAL" = "$REMOTE" ]; then
     echo "PUSH_VERIFIED"
   else
     echo "PUSH_FAILED: local=$LOCAL remote=$REMOTE"
     exit 1
   fi
   ```
   - `PUSH_VERIFIED` が出力されるまでこの Step を完了したと見なしてはならない
   - `PUSH_FAILED`（終了コード1）の場合は `git push origin main` を再実行（必要なら権限昇格）し、再度この検証ゲートを通す
   - **commit はしたが push せずに終了することは絶対にしない**（commit 単独では Slack 投稿が走らないため、過去にこのミスで投稿が漏れた事故がある）
