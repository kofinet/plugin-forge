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

YouTube sometimes blocks anonymous caption downloads. `ingest` and `refresh` then report the
yt-dlp error and exit non-zero. Rerun with your browser's YouTube session:

```bash
py scripts/forge.py ingest --workspace <ws> --cookies-from-browser firefox   # or chrome, edge, ...
py scripts/forge.py ingest --workspace <ws> --cookies path/to/cookies.txt
```

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

## Inspiration

Inspired by [bradautomates/claude-video](https://github.com/bradautomates/claude-video).

## License

[MIT](LICENSE) © COFFEE.NET · Marek Kawa — [github.com/kofinet](https://github.com/kofinet)
