---
description: Match local source-code bundles (zips/folders) to ingested videos and write reference/catalog.md.
argument-hint: "<workspace dir> <sources dir>"
allowed-tools: Bash, Read
---

Match source code to videos: **$ARGUMENTS**

Per the `plugin-forge` skill. Resolve `PY=$(command -v py || command -v python3 || command -v python)`
and run:
```
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" match --workspace "<ws>" --sources "<sources dir>"
```
For each `.zip`/folder it prefers the YouTube link/title in the bundle's `Readme.md`, falling back to
fuzzy name matching against the manifest's video titles. Writes `<ws>/reference/catalog.md`. Review
the `fuzzy:*` rows and fix any weak matches by hand.
