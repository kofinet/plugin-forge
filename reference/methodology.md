# plugin-forge methodology

The playbook the `distill` and `build` steps follow, for any channel/topic.

## Pipeline & artifacts
```
scaffold → ingest → (match) → distill → build → (install)
```
- **Workspace** = the new plugin's directory (`<name>/`). It IS the installable plugin.
- Raw downloads + tracker live under `<name>/.forge/`:
  - `.forge/manifest.json` — channel, plugin name, and per-video `{id,title,url,transcript,frames}`.
  - `.forge/knowledge/<videoId>/transcript.txt` — cleaned, timestamped transcript (the primary
    knowledge source). `frames/` only when ingested with `--frames`.
- The shipped plugin: `.claude-plugin/`, `skills/<name>/SKILL.md`, `commands/*.md`, `reference/*.md`.

## The engine (deterministic steps)
Run via the bundled script (resolve the interpreter: `PY=$(command -v py || command -v python3 || command -v python)`):
`"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" <scaffold|ingest|refresh|status|match|deps> ...`
Requires `yt-dlp` (captions/listing) and, only for `--frames`, `ffmpeg`/`ffprobe`. `deps --state-dir
"${CLAUDE_PLUGIN_DATA}"` checks them once; the `forge-setup` skill installs what is missing.

## Lessons baked in (do these)
1. **Transcripts are the reliable knowledge carrier.** Free captions (`en.vtt`) cover most channels,
   need no API key, and download in seconds (no video). Default to transcripts-only; add `--frames K`
   only when on-screen content (code, slides, UI) matters — frames cost tokens and download the video.
2. **Distill in the main loop or in SMALL parallel batches.** Large fan-outs of subagents can fail
   with transient `529 Overloaded`. If you parallelize, probe with one agent first and cap at ~3–4
   concurrent; otherwise read transcripts directly — they're small (~1–3k words each).
3. **Match source code via its own metadata.** If the user has code bundles, prefer the link/title in
   each bundle's `Readme.md` over fuzzy name matching (`forge match` does this automatically).
4. **Validate before installing.** `claude plugin validate <dir>` → `marketplace add` → `install`.

## distill — turn transcripts into reference docs
Goal: high-signal, citable knowledge the generated skills will use.
1. Read `.forge/knowledge/*/transcript.txt` (and frames if present). They're small; read them all.
2. Identify the **recurring, actionable themes** for the target domain. Write reference docs sized to
   the domain — typical set:
   - `reference/rules.md` — enforceable rules with IDs, **Why**, the **smell** they catch, severity,
     and the source video. (Powers a reviewer/checker skill.)
   - `reference/boilerplates.md` — copy-ready templates/snippets distilled from real examples, each
     citing its source. (Powers a builder/developer skill.) If source code exists, ground these in
     the actual code, lightly cleaned — don't invent.
   - `reference/decisions.md` — decision guides / trade-offs with a default. (Powers an advisor skill.)
   - `reference/catalog.md` — the video (and code) index, with links. `forge match` writes a first cut.
3. Keep every claim grounded in the transcripts/code. Cite videos by title + link. Don't fabricate.
   Adapt the doc set to the topic — a cooking channel yields recipes/techniques, not "rules.md".

## build — assemble the plugin from the reference docs
1. Decide the skill set from the distilled knowledge (e.g. reviewer / developer / advisor, or
   whatever the domain implies). One concern per skill.
2. For each skill, write `skills/<skill>/SKILL.md` with YAML frontmatter
   (`name`, `description` — make the description specific so it auto-triggers, `argument-hint`,
   `allowed-tools`, `user-invocable: true`) and a procedure that **reads the relevant
   `${CLAUDE_PLUGIN_ROOT}/reference/*.md`** then acts. Keep skills thin; put knowledge in reference/.
3. Add a thin `commands/<cmd>.md` slash entry per skill (frontmatter `description`, `argument-hint`,
   `allowed-tools`; body delegates to the skill, using `$ARGUMENTS` and `${CLAUDE_PLUGIN_ROOT}`).
4. Fill `.claude-plugin/plugin.json` (real description + keywords) and `marketplace.json`.
5. Validate, then (if requested) install. Tell the user to restart Claude Code for commands to load.

## House rules for generated plugins
- One concern per skill; knowledge in `reference/`, not inlined in every skill.
- Skill `description` fields must be specific (they drive auto-triggering).
- Reference paths from skills/commands: `${CLAUDE_PLUGIN_ROOT}/reference/<file>`.
- Never invent facts the transcripts/code don't support; cite sources.
