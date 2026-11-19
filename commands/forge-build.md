---
description: Build the new plugin's skills + commands + manifests from the distilled reference docs.
argument-hint: "<workspace dir> [skills to create]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

Build the plugin in: **$ARGUMENTS**

Follow the `build` section of `${CLAUDE_PLUGIN_ROOT}/reference/methodology.md`.
1. From `<ws>/reference/*`, decide the skill set (one concern per skill).
2. Write `<ws>/skills/<skill>/SKILL.md` for each — YAML frontmatter (specific `description` for
   auto-trigger, `argument-hint`, `allowed-tools`, `user-invocable: true`) and a procedure that
   reads the relevant `${CLAUDE_PLUGIN_ROOT}/reference/*.md` then acts. Keep skills thin.
3. Add a thin `<ws>/commands/<cmd>.md` per skill (delegates to the skill via `$ARGUMENTS`).
4. Fill `<ws>/.claude-plugin/plugin.json` + `marketplace.json` (real description + keywords).
5. Validate (`claude plugin validate "<ws>"`) and report. Offer `/forge-install` to install.
