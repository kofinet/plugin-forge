<p align="center">
  <img src="assets/banner.png" alt="plugin-forge — YouTube channel → Claude Code plugin" width="760">
</p>

# plugin-forge

Turn a YouTube channel into a [Claude Code](https://claude.com/claude-code) plugin.

plugin-forge downloads the captions of a channel's newest videos, distills them into citable
reference docs (rules, boilerplates, decision guides, a video catalog) and builds a ready-to-install
plugin with skills and slash commands on top of that knowledge — e.g. a "review my code the way
*&lt;creator&gt;* would" skill, grounded in what the creator actually said, with links to the source videos.

```
scaffold → ingest → (match) → distill → build → (install)
```

## Requirements

- Claude Code
- Python 3.9+ (`py`, `python3` or `python` on PATH) — standard library only
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) on PATH — captions and channel listing
- [`ffmpeg`/`ffprobe`](https://ffmpeg.org/) on PATH — only if you ask for video frames (`--frames`)

You don't have to install them by hand: on the first `/forge` run (or with
`/plugin-forge:forge-setup`) the plugin checks what is there, offers to install what is missing and
remembers a successful check, so later runs skip it. Tools installed outside `PATH` (winget links,
pipx / `pip --user`, Homebrew) are found automatically.

The plugin is the same on Windows, macOS and Linux; only installing the tools differs:

| OS | Python | yt-dlp | ffmpeg (optional) |
|---|---|---|---|
| Windows | `winget install Python.Python.3.12` | `winget install yt-dlp.yt-dlp` | `winget install Gyan.FFmpeg` |
| macOS | `brew install python` (or `python3` from Xcode CLT) | `brew install yt-dlp` | `brew install ffmpeg` |
| Linux | distro package (`python3`) | `pipx install yt-dlp` (distro packages are often too old for YouTube) | `sudo apt install ffmpeg` / `dnf install ffmpeg` |

The examples below use `py` (Windows); on macOS and Linux run `python3` instead.

## Install

```
/plugin marketplace add kofinet/plugin-forge
/plugin install plugin-forge@plugin-forge-marketplace
```

Restart Claude Code so the commands load.

## Usage

The quickest path is the orchestrator — it asks only for what is missing:

```
/forge https://www.youtube.com/@SomeChannel "Some Channel" 20
```

It scaffolds the plugin (in `./<name>` — the current directory — by default), ingests the 20 newest videos'
transcripts, distills them into `reference/`, **shows you the distilled docs before building**, then
writes the skills, commands and manifests and (optionally) installs the result.

Each step is also available on its own:

| Command | What it does |
|---|---|
| `/forge-scaffold <name> [parent dir] [channel]` | Create the plugin skeleton + `.forge/` tracker |
| `/forge-ingest <workspace> [channel] [count] [--frames K]` | Download transcripts (and optional frames) |
| `/forge-match <workspace> <sources dir>` | Map your local code bundles (zips/folders) to videos |
| `/forge-distill <workspace> [focus]` | Write `reference/*.md` from the transcripts |
| `/forge-build <workspace>` | Write skills, commands and manifests from `reference/` |
| `/forge-install <workspace>` | Validate and install the generated plugin locally |
| `/forge-status <workspace>` | Show ingest/build progress |
| `/forge-refresh <workspace> [count]` | Ingest only new videos, then re-distill/rebuild |

The deterministic steps run through `scripts/forge.py`, which you can also call directly:

```bash
py scripts/forge.py ingest --workspace ./my-plugin --channel https://www.youtube.com/@SomeChannel --count 10
```

### "Sign in to confirm you're not a bot"

YouTube sometimes blocks anonymous caption downloads, depending on your IP's reputation and how
many requests it sees. When that happens during `/forge`, the plugin walks through these options
in order and stops at the first one that works:

1. update yt-dlp (an outdated one is a common cause);
2. wait and retry later (the block is often temporary);
3. cookies from a browser you already have, ideally signed in to a separate Google account:
   `--cookies-from-browser <browser>` (yt-dlp's docs warn that an account used for automated
   downloads can be blocked by YouTube);
4. a `cookies.txt` export: `--cookies <file>`;
5. last resort: install Firefox and sign in there with a separate account. yt-dlp reads Firefox's
   cookies reliably on every OS, while Chrome and Edge often fail on Windows (locked, encrypted
   cookie database).

```bash
py scripts/forge.py ingest --workspace <ws> --cookies-from-browser chrome   # one-off, any browser
py scripts/forge.py ingest --workspace <ws> --cookies path/to/cookies.txt
py scripts/forge.py cookies --state-dir <plugin data dir> --browser <browser>  # remember it; --off to stop
```

With a remembered browser, `ingest`/`refresh` (run with the same `--state-dir`) still download
anonymously and switch to that browser's cookies for the rest of the run only when YouTube asks to
sign in. The cookies are read fresh from the browser on every run, so there is nothing to refresh.

The cookies are only passed to yt-dlp. **Never commit a cookies file** — the generated plugin's
`.gitignore` already excludes `cookies*.txt` and `*.cookies`.

## What a generated plugin looks like

```
my-plugin/
├── .claude-plugin/{plugin,marketplace}.json
├── skills/<skill>/SKILL.md      # thin procedures that read reference/
├── commands/<cmd>.md            # slash-command entry points
├── reference/*.md               # distilled, cited knowledge
├── README.md
└── .forge/                      # raw transcripts/frames + manifest (git-ignored)
```

`.forge/` holds raw transcripts of someone else's videos and is git-ignored by default: publish the
distilled plugin, not the source material.

## Content & credit

plugin-forge works with publicly available captions. You are responsible for respecting YouTube's
Terms of Service and the creators' rights: credit the creator in your plugin, cite the source videos
(the distill step does this), and don't redistribute raw transcripts or video frames.

## Development

```bash
py -m unittest discover -s tests
claude plugin validate .
```

CI (`.github/workflows/tests.yml`) runs the tests on Windows, macOS and Linux with Python 3.9 and the
latest 3.x.

## Inspiration

Inspired by [bradautomates/claude-video](https://github.com/bradautomates/claude-video).

## License

[MIT](LICENSE) © COFFEE.NET · Marek Kawa — [github.com/kofinet](https://github.com/kofinet)
