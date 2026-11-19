---
name: forge-setup
description: Check plugin-forge's dependencies once (Python 3.9+, yt-dlp, optional ffmpeg/ffprobe) on Windows, macOS or Linux, install what is missing with the user's OK, and pick up tools installed outside PATH. Use before the first /forge* run, when forge.py says a tool was "not found", when downloads keep failing with YouTube's "not a bot" sign-in check, or when the user asks to set up or repair plugin-forge's dependencies.
argument-hint: "[--recheck]"
allowed-tools: Bash, AskUserQuestion
user-invocable: true
---

# forge-setup — dependencies, checked once

A successful check is remembered in `${CLAUDE_PLUGIN_DATA}/deps.json`. After that the check answers
at once, so this setup only does real work on the first run (or after a tool disappears).
Pass `--recheck` (from `$ARGUMENTS`) to check again anyway.

## 1. Python 3.9+
```bash
PY=$(command -v py || command -v python3 || command -v python)
"$PY" -c "import sys; assert sys.version_info >= (3, 9), sys.version; print(sys.executable)"
```
If `PY` is empty or the check fails (on Windows `python` can be the Microsoft Store stub), Python
must be installed first. Detect the OS with `uname -s` (`MINGW*`/`MSYS*`/`CYGWIN*` = Windows,
`Darwin` = macOS, `Linux`). Ask the user before installing:
- **Windows**: `winget install -e --id Python.Python.3.12`. This shell's PATH is stale afterwards: use
  `"$LOCALAPPDATA/Programs/Python/Launcher/py.exe"` or `"$LOCALAPPDATA"/Programs/Python/Python312/python.exe`.
- **macOS**: `brew install python` when `brew` exists; otherwise `xcode-select --install` (the user
  confirms a system dialog), which provides `/usr/bin/python3`.
- **Linux**: the distro package, e.g. `sudo apt-get install -y python3` or `sudo dnf install -y python3`.

## 2. Check the tools
```bash
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" deps --state-dir "${CLAUDE_PLUGIN_DATA}" [--recheck]
```
- Exit 0 → dependencies are fine; say so in one line and stop.
- `[ok] … (not on PATH; forge uses this path directly)` needs no action: forge finds tools in the
  usual install locations (winget links, pipx/pip `--user` scripts, Homebrew, scoop, Chocolatey, snap).
- `[missing] … install: <command>` lines carry the install command for this machine.

## 3. Install what is missing
Ask once with AskUserQuestion (multi-select): **yt-dlp** (required, recommended) and **ffmpeg**
(optional, only for `--frames`). Install only what the user picked; never install without asking.
- Commands without `sudo`: run them yourself, one at a time, and report failures verbatim.
- Commands with `sudo` need the user's password: ask the user to run them as `! <command>`.
- "no supported package manager found": point to https://github.com/yt-dlp/yt-dlp#installation and
  https://ffmpeg.org/download.html, or on macOS suggest Homebrew (https://brew.sh) first.

## 4. Check again
Run step 2 with `--recheck` until it prints `ready`. A fresh install is usually not on this shell's
PATH yet; that is expected and fine. If a tool still shows `[missing]` after a successful install,
ask the user where it was installed rather than editing their shell profile or PATH.

Report what was found where and what was installed, and that later /forge* runs skip this check.
Do not bring up cookies or browsers during setup: that is only for the sign-in check below.

## When YouTube keeps asking to sign in ("not a bot")
YouTube sometimes refuses anonymous downloads ("Sign in to confirm you're not a bot"), depending on
the IP's reputation and the number of requests. `ingest`/`refresh` with `--state-dir` already retry
once with a remembered browser's cookies (`cookies fallback` in the `deps` output). When a download
still fails with that error, go down this ladder **in order**, one step at a time, retrying the same
`ingest`/`refresh` after each step and stopping at the first one that works. Ask before each step that
installs software or uses an account.

1. **Update yt-dlp.** YouTube changes often and an outdated yt-dlp is a common cause. Use the
   installer the `deps` path points to: WinGet `Links` → `winget upgrade -e --id yt-dlp.yt-dlp`;
   Homebrew → `brew upgrade yt-dlp`; pipx (`~/.local/bin`) → `pipx upgrade yt-dlp`; pip `--user` →
   `"$PY" -m pip install -U --user yt-dlp`; a standalone binary → `yt-dlp -U`.
2. **Wait and retry later.** The block is often temporary. Suggest retrying in an hour or so (fewer
   videos per run helps); don't loop retries.
3. **A browser the user already has.** Ask which browser they are signed in to YouTube with and
   retry once with `--cookies-from-browser <browser>`. Warn first: yt-dlp's docs say an account used
   for automated downloads can be temporarily or permanently blocked by YouTube, so a separate Google
   account (or a separate browser profile, `<browser>:<profile>`) is safer than the main one. If it
   works, offer to remember it: `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" cookies --state-dir
   "${CLAUDE_PLUGIN_DATA}" --browser <browser>`. On Windows Chrome/Edge often fail to give cookies
   ("could not copy/decrypt cookie database"); closing the browser first sometimes helps.
4. **A cookies.txt export.** If the user can export YouTube cookies (Netscape format) from a browser
   extension, retry with `--cookies <file>`. Keep the file outside the workspace and never commit it.
5. **Last resort: install Firefox** — only when every step above failed. Explain why:
   - yt-dlp reads Firefox's cookies straight from its profile on Windows, macOS and Linux, while
     Chrome and Edge often fail (locked, encrypted cookie database).
   - A fresh Firefox signed in to a separate Google account keeps the main account out of the risk.
   - Cookies are read fresh on every run, so nothing needs refreshing while the account stays signed in.
   Install with the user's OK: Windows `winget install -e --id Mozilla.Firefox`; macOS
   `brew install --cask firefox` (or https://www.mozilla.org/firefox/); Linux the distro package
   (e.g. `sudo apt-get install -y firefox`, which the user runs as `! <command>`). After the user has
   signed in to YouTube in Firefox with the separate account, remember it with
   `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/forge.py" cookies --state-dir "${CLAUDE_PLUGIN_DATA}" --browser firefox`
   and retry.

If all of this fails, report the last yt-dlp error verbatim. Never try to get around YouTube's check
by other means (e.g. switching yt-dlp's player clients).
