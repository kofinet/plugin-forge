---
description: Validate, register, and install the generated plugin locally (claude plugin marketplace add + install).
argument-hint: "<workspace dir>"
allowed-tools: Bash, Read
---

Install the generated plugin in: **$ARGUMENTS**

Per the `plugin-forge` skill:
1. `claude plugin validate "<ws>"` — fix any manifest errors first.
2. `claude plugin marketplace add "<ws>"`.
3. Read `<ws>/.claude-plugin/marketplace.json` for the marketplace name and plugin slug, then
   `claude plugin install <slug>@<marketplace-name>`.
4. Confirm with `claude plugin list` and tell the user to **restart Claude Code** for the new
   commands/skills to load. Report the available `/`-commands the new plugin exposes.
