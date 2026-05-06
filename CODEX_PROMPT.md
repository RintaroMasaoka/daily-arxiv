# Codex Scheduled Task Prompt

Use this prompt when creating a Codex scheduled task for the production digest:

```text
Use $daily-arxiv-digest and follow the repository instructions in AGENTS.md.
```

If the skill is not installed in the scheduled-task environment, use this fallback prompt:

```text
Read AGENTS.md and follow the instructions exactly.
```

If the environment does not auto-discover repo-local skills, install `.codex/skills/daily-arxiv-digest` into the Codex skill directory before using the `$daily-arxiv-digest` prompt.

The task needs permission to push to `main`, because the GitHub Actions workflows are triggered by commits to `data/trigger.txt` and `output/result.md`.
