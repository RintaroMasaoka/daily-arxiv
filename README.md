# arxiv-digest

arXiv新着論文の自動選出・Slack共有。Claude Code cloud scheduled taskで動作する。

## リポジトリ構成

```
├── prompt.md          # タスクプロンプト（claude.ai/code/scheduled に貼る）
├── fetch_papers.py    # arXiv API から論文を取得するスクリプト
├── rules.md           # 選出ルール（自由記述、手動で編集）
├── history.json       # 選出履歴＋フィードバック（タスクが自動更新）
└── README.md          # このファイル
```

## セットアップ

### 1. このリポジトリをGitHubにpush

```bash
git init
git add -A
git commit -m "initial commit"
git remote add origin git@github.com:<your-username>/arxiv-digest.git
git push -u origin main
```

### 2. Cloud scheduled task を作成

1. https://claude.ai/code/scheduled にアクセス
2. 「New scheduled task」をクリック
3. 以下を設定：
   - **Name**: arXiv Daily Digest
   - **Prompt**: `prompt.md` の内容をコピー＆ペースト
   - **Repository**: このリポジトリを接続。**「Allow unrestricted branch pushes」を有効にする**（history.json を main に直接 push するため）
   - **Schedule**: 平日毎朝（例: HKT 10:00 = UTC 02:00 → `0 2 * * 1-5`）
   - **Connectors**: Slack を接続
   - **Environment**: ネットワークアクセスを有効にする（arXiv API へのHTTPリクエストに必要）

### 3. 動作確認

タスクを手動実行し、以下を確認：
- `fetch_papers.py` が正常に論文を取得している
- Slack の `share-paper` チャンネルにメッセージが投稿される
- `history.json` が更新され、main にpushされている

## 運用

### 選出ルールの変更

`rules.md` を直接編集してコミット。自然言語で記述する。

```
# 例
Hastingsの論文は常に拾う
量子情報と物性の接点に関する論文は優先度を上げる
スピン液体のVMC計算は、一般的な知見がない限り除外
```

### フィードバックの記録

`history.json` の該当エントリの `feedback` フィールドを編集する：

```json
{
  "id": "2506.12345",
  "title": "...",
  "date_selected": "2026-04-01",
  "feedback": {
    "rating": "positive",
    "reason": "対称性と絡み合いの接続が意外。こういう論文をもっと拾ってほしい"
  }
}
```

`rating` は `"positive"` または `"negative"`。`reason` は任意だが、書くほど選出精度が上がる。

### 履歴の肥大化

`history.json` は追記のみで成長する。重複排除に使うのはIDだけなので、古いエントリの `title` / `feedback` を削除しても動作する。フィードバックが十分に蓄積したら（目安: 数ヶ月分）、古い feedback なしエントリを ID だけに圧縮してよい：

```json
{"id": "2506.12345"}
```