---
description: Forge a whole Claude Code plugin from a YouTube channel — orchestrates scaffold → ingest → (match) → distill → build → install.
argument-hint: "<channel url> [plugin name] [count]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, AskUserQuestion
---

Forge a new plugin from: **$ARGUMENTS**

Follow the `plugin-forge` skill end-to-end. Read `${CLAUDE_PLUGIN_ROOT}/reference/methodology.md` first.

1. Gather inputs (use AskUserQuestion only for what's missing): channel URL, plugin name, video
   count, frames yes/no, do they have source code to match, auto-install yes/no.
2. **Scaffold** the plugin (`forge.py scaffold`), then **ingest** the N newest videos
   (`forge.py ingest`, transcripts by default).
3. If they have code bundles, **match** them (`forge.py match`).
4. **Distill** the transcripts into `reference/` docs — then SHOW the user the distilled docs and
   pause for adjustments before building.
5. **Build** the skills + commands + manifests from the reference docs.
6. If requested, **validate + install** and tell the user to restart Claude Code.

Resolve the interpreter as `PY=$(command -v py || command -v python3 || command -v python)` and call
`"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" ...`. Keep the user in the loop on scope decisions.
