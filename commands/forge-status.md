---
description: Show a plugin workspace's forge status — channel, ingested videos, transcripts, frames, build progress.
argument-hint: "<workspace dir>"
allowed-tools: Bash, Read, Glob
---

Show forge status for: **$ARGUMENTS**

Resolve `PY=$(command -v py || command -v python3 || command -v python)` and run:
```
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" status --workspace "<ws>"
```
Then also note build progress by checking the workspace: which `reference/*.md` exist (distilled?),
which `skills/*/SKILL.md` and `commands/*.md` exist (built?), and whether the plugin is installed
(`claude plugin list`). Summarize what's done and the next step (ingest / distill / build / install).
