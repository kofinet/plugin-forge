---
description: Download the N newest videos from a channel (transcripts + optional frames) into a plugin workspace.
argument-hint: "<workspace dir> [channel url] [count] [--frames K]"
allowed-tools: Bash, Read, AskUserQuestion
---

Ingest videos: **$ARGUMENTS**

Per the `plugin-forge` skill. Resolve `PY=$(command -v py || command -v python3 || command -v python)`
and run:
```
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" ingest --workspace "<ws>" [--channel "<url>"] --count N [--frames K | --no-frames] [--videos id1,id2] [--force] [--cookies-from-browser <browser>] --state-dir "${CLAUDE_PLUGIN_DATA}"
```
Default is transcripts-only (fast, free, no API key — uses captions). Add `--frames K` only when
on-screen content matters (it downloads the video and costs more). Transcripts land in
`<ws>/.forge/knowledge/<id>/transcript.txt` and the manifest is updated. Report how many transcripts
were captured and any per-video errors. Videos that already have a transcript are skipped unless
`--force`. If YouTube asks to sign in ("not a bot"), forge retries with the remembered browser's
cookies on its own; if it still fails, follow the sign-in ladder of the `forge-setup` skill, in order. Needs `yt-dlp` (and
`ffmpeg` for frames): first run `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" deps --state-dir "${CLAUDE_PLUGIN_DATA}"`
and, if it fails, follow the `forge-setup` skill.
