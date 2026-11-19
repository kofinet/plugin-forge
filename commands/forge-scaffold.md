---
description: Scaffold a new plugin project skeleton (manifests + skills/commands/reference dirs + .forge tracker).
argument-hint: "<plugin name> [parent dir] [channel url]"
allowed-tools: Bash, Read, AskUserQuestion
---

Scaffold a new plugin: **$ARGUMENTS**

Per the `plugin-forge` skill. Resolve `PY=$(command -v py || command -v python3 || command -v python)`
and run:
```
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" scaffold --name "<Name>" [--dir "<parent>"] [--channel "<url>"]
```
Pass `--dir` only when the user named a parent dir; otherwise the plugin lands in the current
directory.
This creates `<parent>/<Name>/` with `.claude-plugin/{plugin,marketplace}.json`, `skills/`,
`commands/`, `reference/`, and `.forge/manifest.json`. Report the workspace path and the install id
(`<slug>@<slug>-marketplace`). Ask for the name/parent only if not given.
