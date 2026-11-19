---
description: Distill ingested transcripts into reference docs (rules / boilerplates / decisions / catalog) for the new plugin.
argument-hint: "<workspace dir> [focus/domain hint]"
allowed-tools: Read, Write, Grep, Glob, Bash
---

Distill knowledge for: **$ARGUMENTS**

Follow the `distill` section of `${CLAUDE_PLUGIN_ROOT}/reference/methodology.md`.
1. Read every `<ws>/.forge/knowledge/*/transcript.txt` (and frames if present). They're small —
   read them directly. If you parallelize with subagents, probe one first and cap at ~3–4 (transient
   529s are possible).
2. Identify the recurring, actionable themes for the domain and write `<ws>/reference/` docs sized to
   the topic — typically `rules.md`, `boilerplates.md`, `decisions.md`, and `catalog.md` (whichever
   fit; a non-code channel yields different docs).
3. Ground every claim in the transcripts/code and cite video titles + links. Do not invent.
4. Show the user the distilled docs and confirm before `/forge-build`.
