---
name: plugin-forge
description: Forge a new Claude Code plugin from a YouTube channel — scaffold a plugin project, download videos (transcripts + optional frames) from a channel, distill the knowledge into reference docs, and build a plugin with skills and commands. Use when the user wants to turn a channel/creator's videos (and optionally their source code) into a reusable plugin, or runs any /forge* command.
argument-hint: "<channel url> [plugin name] [count]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, AskUserQuestion
homepage: https://github.com/kofinet/plugin-forge
user-invocable: true
---

# plugin-forge — build a plugin from a video channel

Turns a channel's videos into a plugin grounded in what the creator actually said. The full playbook is in
**`${CLAUDE_PLUGIN_ROOT}/reference/methodology.md`** — read it before distilling or building.

## Engine
Deterministic steps run through the bundled script. Resolve the interpreter once:
```bash
PY=$(command -v py || command -v python3 || command -v python)
FORGE="${CLAUDE_PLUGIN_ROOT}/scripts/forge.py"
```
Requires `yt-dlp` (captions + channel listing); `ffmpeg`/`ffprobe` only for `--frames`.
Before the first `forge.py` call, check the dependencies (instant after the first successful check):
```bash
"$PY" "$FORGE" deps --state-dir "${CLAUDE_PLUGIN_DATA}"
```
If `PY` is empty, the check exits non-zero, or a later call says a tool was "not found", follow the
`forge-setup` skill (`plugin-forge:forge-setup`) first, then continue.

## Pipeline (also exposed as individual /forge* commands)
1. **Scaffold** — `"$PY" "$FORGE" scaffold --name "<Name>" [--dir "<parent>"] --channel "<url>"`.
   Pass `--dir` only if the user named a parent; the default parent is the current directory.
   Creates `<parent>/<Name>/` with `.claude-plugin/`, `skills/`, `commands/`, `reference/`, and
   `.forge/manifest.json`. The workspace = `<parent>/<Name>`.
2. **Ingest** — `"$PY" "$FORGE" ingest --workspace "<ws>" --channel "<url>" --count N [--frames K] --state-dir "${CLAUDE_PLUGIN_DATA}"`.
   Downloads the N newest videos' transcripts (and K frames each if asked) into `.forge/knowledge/`.
   Default is transcripts-only (fast, reliable, free); add `--frames` only if visuals matter.
   Already-ingested videos are skipped (`--force` re-downloads). With `--state-dir`, YouTube's
   "Sign in to confirm you're not a bot" is retried automatically with the remembered browser's
   cookies. If it still fails, follow the "When YouTube keeps asking to sign in" ladder of the
   `forge-setup` skill, in order (installing Firefox is only its last step). Never copy cookies into
   the workspace.
3. **Match** (optional) — if the user has code bundles: `"$PY" "$FORGE" match --workspace "<ws>"
   --sources "<dir>"` → writes `reference/catalog.md` (prefers each bundle's Readme link).
4. **Distill** — read `.forge/knowledge/*/transcript.txt` and write `reference/` docs
   (rules.md / boilerplates.md / decisions.md / catalog.md as the domain warrants). Per
   methodology.md: read transcripts directly (they're small); if parallelizing, probe one agent
   first and cap at ~3–4 (transient 529s). Ground every claim in sources; cite video titles+links.
5. **Build** — design the skill set, write `skills/<skill>/SKILL.md` (specific `description`,
   `user-invocable: true`, procedure that reads `${CLAUDE_PLUGIN_ROOT}/reference/*`), thin
   `commands/<cmd>.md` entries, and fill the manifests.
6. **Install** (optional) — `claude plugin validate "<ws>"` → `claude plugin marketplace add "<ws>"`
   → `claude plugin install <slug>@<slug>-marketplace`. Tell the user to restart Claude Code.

## Orchestrator behavior (`/forge`)
Run the whole pipeline. Ask the user (AskUserQuestion) only for what's missing: channel URL, plugin
name, video count, frames yes/no, whether they have source code to match, and whether to auto-install.
Then execute steps 1→6, pausing to show the distilled reference docs before building so the user can
adjust. Keep the user in the loop; don't silently make scope decisions.

## Status / refresh
- `"$PY" "$FORGE" status --workspace "<ws>"` — manifest summary.
- `"$PY" "$FORGE" refresh --workspace "<ws>" [--count N]` — ingest only videos newer than the
  manifest, then re-run distill/build for the new material.

Keep generated plugins clean: one concern per skill, knowledge in `reference/`, specific skill
descriptions, no invented facts.
