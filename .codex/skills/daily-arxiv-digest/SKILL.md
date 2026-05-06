---
name: daily-arxiv-digest
description: Run the Daily arXiv Digest workflow in this repository. Use when Codex is asked to fetch new arXiv papers, select papers using criteria.md, update output/result.md, update data/last_processed.json, or publish the digest through the repository's GitHub Actions and Slack webhook flow.
---

# Daily arXiv Digest

## Overview

Execute the production digest workflow from this repository. Use `AGENTS.md` as the source of truth for the operational steps, and use `criteria.md` as the source of truth for paper selection.

## Workflow

1. Read `AGENTS.md` completely before taking action.
2. Follow Step 0 exactly: switch to `main`, pull, push `data/trigger.txt`, then poll for a changed `data/latest.json`.
3. If polling returns `TIMEOUT`, stop. Do not process the previous `data/latest.json`.
4. Read `data/latest.json` and `data/last_processed.json`; exclude papers whose `arxiv_id` is already in `seen_ids`.
5. If `papers` is empty or every paper is already seen, stop without posting or pushing a result.
6. Read `criteria.md`, rank the unseen papers by the stated research criteria, and select roughly 3 to 7 papers unless the day genuinely warrants fewer or none.
7. Write only the selected paper list to `output/result.md` in the exact Slack mrkdwn format from `AGENTS.md`.
8. Append any missed-paper warning required by `total_results`.
9. Update `data/last_processed.json` by adding all paper IDs from the current `latest.json`, not only selected papers.
10. Commit and push `output/result.md` and `data/last_processed.json` to `main`. GitHub Actions posts to Slack; do not post to Slack directly.

## Codex Notes

- The Codex environment may not be able to access `export.arxiv.org`; always delegate fetching to GitHub Actions through the trigger file.
- Networked `git pull` and `git push` may require permission in interactive runs. If a git command fails because of sandbox or network restrictions, rerun the same command with escalation instead of changing the workflow.
- The initial branch for scheduled runs may be `codex/*` or `Codex/*`. The production workflow must run on `main`.
- Treat `data/latest.json`, `data/last_processed.json`, and `output/result.md` as production state. Do not rewrite them for dry runs unless the user explicitly asks for a dry run.
- Preserve unrelated user changes in the worktree.

## Output Rules

- `output/result.md` must contain no scores, summaries, categories, or explanatory text beyond the optional missed-paper warning.
- Use the selected order from the criteria-based ranking.
- If zero papers are selected after criteria evaluation but there were unseen papers, write an empty `output/result.md`, update `data/last_processed.json`, and push those state changes so the same papers are not reconsidered tomorrow.
