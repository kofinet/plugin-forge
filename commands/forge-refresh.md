---
description: Incrementally ingest only videos newer than the manifest, then re-distill/rebuild for the new material.
argument-hint: "<workspace dir> [count]"
allowed-tools: Bash, Read, Write, Grep, Glob
---

Refresh: **$ARGUMENTS**

Per the `plugin-forge` skill. Resolve `PY=$(command -v py || command -v python3 || command -v python)`
and run:
```
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" refresh --workspace "<ws>" [--count N] [--frames K] [--cookies-from-browser <browser>]
```
It compares the channel's newest against the manifest and ingests only the new videos. Then update
the `reference/` docs for the new transcripts (re-distill) and, if skills changed, rebuild and offer
to reinstall. Report what was new.
