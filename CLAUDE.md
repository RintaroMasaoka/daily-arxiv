# Daily arXiv Digest

このタスクは2段階のパイプラインの後半である。GitHub Actions が毎朝 arXiv API から新着論文を取得し `data/latest.json` に保存する。このタスク（Claude Code Scheduled Task）は、そのJSONを読み込み、`criteria.md` に定義された基準に従って論文を選別し、`output/result.md` に書き出して main ブランチに push する。push をトリガーに GitHub Actions が Slack へ投稿する。

---

## Step 1: 論文データの読み込み

リポジトリ内の `data/latest.json` を読み込む。

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

### 取得0件の場合

`papers` が空配列の場合は、何も送信せず終了する。

---

## Step 2: 論文の選別

`criteria.md` を読み込み、そこに定義された基準とプロセスに従って論文を選別する。

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
2. main ブランチに切り替える: `git checkout main && git pull origin main`
3. `output/result.md` を commit & push する（このファイルの変更が GitHub Actions の Slack 投稿をトリガーする）

**重要**: Scheduled Task は `claude/*` ブランチ上で開始されるが、Slack 投稿のトリガーは main ブランチへの push であるため、必ず main に切り替えてから push すること。
