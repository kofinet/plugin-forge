#!/usr/bin/env python3
"""plugin-forge engine: turn a YouTube channel into the raw material for a Claude Code plugin.

Subcommands (deterministic steps; distill & build are LLM-driven and live in the commands):
  scaffold  --name NAME [--dir DIR]                 create an installable plugin skeleton
                                                    (DIR defaults to the current directory)
  ingest    --workspace DIR --channel URL --count N [--videos a,b] [--frames K] [--no-frames] [--force]
  refresh   --workspace DIR [--count N]             ingest only videos newer than the manifest
  status    --workspace DIR                         print the manifest summary
  match     --workspace DIR --sources DIR           map local code zips/folders to ingested videos

ingest/refresh also take --cookies-from-browser BROWSER or --cookies FILE, passed straight to
yt-dlp, for when YouTube answers "Sign in to confirm you're not a bot".

Requires `yt-dlp` and (for frames) `ffmpeg`/`ffprobe` on PATH. Transcripts use free captions.
The workspace is the plugin dir; raw downloads + manifest live under <workspace>/.forge/.
"""
from __future__ import annotations
import argparse, json, string, subprocess, sys, zipfile
from pathlib import Path

SLUG_CHARS = set(string.ascii_lowercase + string.digits + "-")
WORD_CHARS = set(string.ascii_lowercase + string.digits)
YOUTUBE_LINK_PREFIXES = ("https://youtu", "http://youtu")
COOKIES_HINT = ("YouTube may be asking to sign in: rerun with --cookies-from-browser <browser> "
                "or --cookies <cookies.txt> (never commit cookie files).")

GENERATED_GITIGNORE = """\
# plugin-forge working data: raw transcripts/frames of other people's videos.
# Keep it local; publish only the distilled plugin.
.forge/
cookies*.txt
*.cookies
__pycache__/
"""


# ---------- helpers ----------
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def manifest_path(ws: Path) -> Path:
    return ws / ".forge" / "manifest.json"


def load_manifest(ws: Path) -> dict:
    p = manifest_path(ws)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"pluginName": ws.name, "channel": None, "videos": []}


def save_manifest(ws: Path, m: dict) -> None:
    p = manifest_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")


def parse_cue_start(line: str) -> int | None:
    """Seconds from a VTT cue timing line ('HH:MM:SS.mmm --> ...'), or None if it isn't one."""
    if "-->" not in line:
        return None
    parts = line.split("-->", 1)[0].strip().split(".", 1)[0].split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() and len(p) == 2 for p in parts):
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + int(p)
    return seconds


def strip_tags(s: str) -> str:
    """Remove '<...>' markup (VTT voice/class/timestamp tags)."""
    out, pos = [], 0
    while True:
        start = s.find("<", pos)
        end = s.find(">", start + 1) if start != -1 else -1
        if start == -1 or end == -1:
            out.append(s[pos:])
            return "".join(out)
        out.append(s[pos:start])
        pos = end + 1


def clean_vtt(path: Path) -> str:
    """Turn a clean (non-rolling) en.vtt into '[MM:SS] text' paragraphs (~15s)."""
    cues, start, buf = [], None, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cue_start = parse_cue_start(line)
        if cue_start is not None:
            if start is not None and buf:
                cues.append((start, _clean(" ".join(buf))))
            start = cue_start
            buf = []
        elif line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:")):
            buf.append(line)
    if start is not None and buf:
        cues.append((start, _clean(" ".join(buf))))
    cues = [(t, x) for t, x in cues if x]
    # group into ~15s paragraphs, de-duping consecutive identical text
    paras, cs, cur, prev = [], None, [], None
    for t, x in cues:
        if x == prev:
            continue
        prev = x
        if cs is None:
            cs = t
        if t - cs >= 15 and cur:
            paras.append((cs, " ".join(cur)))
            cs, cur = t, []
        cur.append(x)
    if cur:
        paras.append((cs, " ".join(cur)))
    return "\n".join(f"[{t//60:02d}:{t%60:02d}] {x}" for t, x in paras)


def _clean(s: str) -> str:
    s = strip_tags(s).replace("&nbsp;", " ").replace(" ", " ")
    return " ".join(s.split())


def slugify(name: str) -> str:
    return "".join(c if c in SLUG_CHARS else "-" for c in name.lower()).strip("-")


def words(s: str) -> set[str]:
    """Lower-case ASCII letter/digit runs, for fuzzy title matching."""
    return {w for w in "".join(c if c in WORD_CHARS else " " for c in s.lower()).split()}


def find_youtube_link(markdown: str) -> tuple[str, str] | None:
    """First '[title](https://youtu...)' link in a Markdown text, as (title, url)."""
    pos = 0
    while (mid := markdown.find("](", pos)) != -1:
        pos = mid + 2
        open_ = markdown.rfind("[", 0, mid)
        close = markdown.find(")", mid + 2)
        if open_ == -1 or close == -1:
            continue
        title, url = markdown[open_ + 1:mid], markdown[mid + 2:close]
        if title and "]" not in title and any(url.startswith(p) and len(url) > len(p) for p in YOUTUBE_LINK_PREFIXES):
            return title, url
    return None


def yt_dlp_error(stderr: str) -> str:
    """The ERROR line(s) yt-dlp printed, else its last non-empty line."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    return " | ".join(errors) if errors else (lines[-1] if lines else "yt-dlp failed")


def auth_args(a) -> list[str]:
    """yt-dlp authentication flags from the CLI args (never logged)."""
    if getattr(a, "cookies_from_browser", None):
        return ["--cookies-from-browser", a.cookies_from_browser]
    if getattr(a, "cookies", None):
        return ["--cookies", a.cookies]
    return []


def newest(channel: str, count: int | None, auth: list[str] | None = None) -> list[dict]:
    args = ["yt-dlp", "--flat-playlist", "--no-warnings", "--print", "%(id)s\t%(title)s", *(auth or [])]
    if count:
        args += ["--playlist-end", str(count)]
    url = channel if "/videos" in channel or "list=" in channel else channel.rstrip("/") + "/videos"
    cp = run(args + [url])
    if cp.returncode != 0:
        print(cp.stderr, file=sys.stderr)
        raise SystemExit(f"yt-dlp failed listing channel: {channel}\n{COOKIES_HINT}")
    out = []
    for line in cp.stdout.splitlines():
        if "\t" in line:
            vid, title = line.split("\t", 1)
            out.append({"id": vid.strip(), "title": title.strip(), "url": f"https://www.youtube.com/watch?v={vid.strip()}"})
    return out


def ffprobe_duration(video: Path) -> float:
    cp = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(video)])
    try:
        return float(cp.stdout.strip())
    except ValueError:
        return 0.0


def download_one(vid: dict, vdir: Path, frames: int, auth: list[str] | None = None) -> dict:
    vdir.mkdir(parents=True, exist_ok=True)
    rec = {**vid, "transcript": False, "frames": 0}
    # 1) captions (no video download) — fast & free
    cp = run(["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
              "--sub-langs", "en,en-orig,en.*", "--sub-format", "vtt", "--convert-subs", "vtt",
              "--no-warnings", *(auth or []), "-o", str(vdir / "video.%(ext)s"), vid["url"]])
    vtts = sorted(vdir.glob("video*.vtt"))
    clean = next((v for v in vtts if v.name == "video.en.vtt"), vtts[0] if vtts else None)
    if clean:
        text = clean_vtt(clean)
        if text:
            (vdir / "transcript.txt").write_text(f"# {vid['title']}\n{vid['url']}\n\n{text}\n", encoding="utf-8")
            rec["transcript"] = True
    if not rec["transcript"]:
        rec["error"] = yt_dlp_error(cp.stderr) if cp.returncode != 0 else "no English captions available"
    # 2) optional frames (downloads the video, then ffmpeg)
    if frames > 0:
        cp = run(["yt-dlp", "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                  "--no-warnings", *(auth or []), "-o", str(vdir / "src.%(ext)s"), vid["url"]])
        src = next((p for p in vdir.glob("src.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm")), None)
        if src:
            dur = ffprobe_duration(src) or 600
            fps = max(0.05, min(1.0, frames / dur))
            fdir = vdir / "frames"
            fdir.mkdir(exist_ok=True)
            run(["ffmpeg", "-y", "-i", str(src), "-vf", f"fps={fps:.4f},scale=512:-1",
                 "-qscale:v", "5", str(fdir / "frame_%04d.jpg")])
            rec["frames"] = len(list(fdir.glob("*.jpg")))
            try:
                src.unlink()  # keep frames, drop the heavy video
            except OSError:
                pass
        elif cp.returncode != 0:
            rec["frames_error"] = yt_dlp_error(cp.stderr)
    return rec


def generated_readme(name: str, slug: str, channel: str | None) -> str:
    source = f"the YouTube channel {channel}" if channel else "a YouTube channel"
    return (
        f"# {name}\n\n"
        f"A Claude Code plugin generated by [plugin-forge](https://github.com/kofinet/plugin-forge) from {source}.\n"
        "Its skills and commands draw on reference docs distilled from the channel's videos, and every "
        "claim cites its source video.\n\n"
        "## Install\n\n"
        "```\n"
        f"/plugin marketplace add <path-or-github-repo>\n"
        f"/plugin install {slug}@{slug}-marketplace\n"
        "```\n\n"
        "## Credits\n\n"
        "The knowledge in `reference/` comes from the creator's public videos; all credit goes to them. "
        "Raw transcripts stay in `.forge/` (git-ignored) and are not redistributed.\n"
    )


# ---------- subcommands ----------
def cmd_scaffold(a):
    base = Path(a.dir).resolve() if a.dir else Path.cwd()
    ws = base / a.name
    slug = slugify(a.name)
    if not slug.replace("-", ""):
        raise SystemExit(f"plugin name must contain ASCII letters or digits: {a.name!r}")
    for sub in [".claude-plugin", "commands", "reference", f"skills", ".forge/knowledge"]:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    (ws / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": slug, "version": "0.1.0",
        "description": f"{a.name} — generated by plugin-forge from a video channel.",
        "author": {"name": a.author or "forge"}, "license": "MIT", "keywords": []
    }, indent=2), encoding="utf-8")
    (ws / ".claude-plugin" / "marketplace.json").write_text(json.dumps({
        "name": f"{slug}-marketplace",
        "metadata": {"description": f"{a.name} (generated by plugin-forge)."},
        "owner": {"name": a.author or "forge"},
        "plugins": [{"name": slug, "description": a.name, "source": "./", "category": "generated"}]
    }, indent=2), encoding="utf-8")
    gitignore = ws / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GENERATED_GITIGNORE, encoding="utf-8")
    readme = ws / "README.md"
    if not readme.exists():
        readme.write_text(generated_readme(a.name, slug, a.channel), encoding="utf-8")
    m = load_manifest(ws)
    m.update({"pluginName": slug, "channel": a.channel})
    save_manifest(ws, m)
    print(f"scaffolded plugin '{slug}' at {ws}")
    print(f"  install id: {slug}@{slug}-marketplace")


def cmd_ingest(a):
    ws = Path(a.workspace).resolve()
    m = load_manifest(ws)
    if a.channel:
        m["channel"] = a.channel
    frames = 0 if a.no_frames else a.frames
    auth = auth_args(a)
    if a.videos:
        ids = [v.strip() for v in a.videos.split(",") if v.strip()]
        vids = [{"id": i, "title": i, "url": f"https://www.youtube.com/watch?v={i}"} for i in ids]
    else:
        if not m.get("channel"):
            raise SystemExit("no --channel and none in manifest")
        vids = newest(m["channel"], a.count, auth)
    have = {v["id"] for v in m["videos"] if v.get("transcript") and (frames == 0 or v.get("frames"))}
    todo = vids if a.force else [v for v in vids if v["id"] not in have]
    if len(todo) < len(vids):
        print(f"skipping {len(vids) - len(todo)} already-ingested video(s); use --force to re-download")
    failed = []
    for i, vid in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {vid['id']} {vid['title'][:60]}")
        rec = download_one(vid, ws / ".forge" / "knowledge" / vid["id"], frames, auth)
        if rec.get("error"):
            print(f"    no transcript: {rec['error']}", file=sys.stderr)
            failed.append(rec)
        m["videos"] = [v for v in m["videos"] if v["id"] != vid["id"]] + [rec]
    save_manifest(ws, m)
    print(f"ingested {len(todo) - len(failed)}/{len(todo)} videos (frames={frames}); transcripts in workspace: "
          f"{sum(1 for v in m['videos'] if v.get('transcript'))}/{len(m['videos'])}")
    if todo and len(failed) == len(todo):
        raise SystemExit(f"no transcript captured for any of {len(todo)} video(s).\n{COOKIES_HINT}")


def cmd_refresh(a):
    ws = Path(a.workspace).resolve()
    m = load_manifest(ws)
    if not m.get("channel"):
        raise SystemExit("no channel in manifest; run ingest first")
    have = {v["id"] for v in m["videos"]}
    fresh = [v for v in newest(m["channel"], a.count, auth_args(a)) if v["id"] not in have]
    if not fresh:
        print("nothing new")
        return
    print(f"{len(fresh)} new video(s)")
    a.videos = ",".join(v["id"] for v in fresh)
    a.channel = None
    cmd_ingest(a)


def cmd_status(a):
    ws = Path(a.workspace).resolve()
    m = load_manifest(ws)
    print(f"plugin: {m.get('pluginName')}   channel: {m.get('channel')}")
    print(f"videos: {len(m['videos'])}   transcripts: {sum(1 for v in m['videos'] if v.get('transcript'))}"
          f"   with frames: {sum(1 for v in m['videos'] if v.get('frames'))}")
    for v in m["videos"][:60]:
        flag = "T" if v.get("transcript") else "-"
        err = f"  ! {v['error'][:80]}" if v.get("error") else ""
        print(f"  [{flag}] {v['id']}  {v.get('title','')[:60]}  frames={v.get('frames',0)}{err}")


def cmd_match(a):
    ws = Path(a.workspace).resolve()
    m = load_manifest(ws)
    src = Path(a.sources).resolve()
    if not src.is_dir():
        raise SystemExit(f"sources dir not found: {src}")
    titles = [(v["id"], v.get("title", ""), v["url"]) for v in m["videos"]]

    rows = []
    items = list(src.glob("*.zip")) + [p for p in src.iterdir() if p.is_dir()]
    for it in items:
        found = None
        if it.suffix == ".zip":
            try:
                with zipfile.ZipFile(it) as z:
                    rm = next((n for n in z.namelist() if n.lower().endswith("readme.md") and "__macosx" not in n.lower()), None)
                    if rm:
                        found = find_youtube_link(z.read(rm).decode("utf-8", "replace"))
            except zipfile.BadZipFile:
                pass
        if found:
            rows.append((it.name, found[0], found[1], "readme"))
            continue
        # fall back to fuzzy name match against video titles
        key = words(it.stem.replace("code-", ""))
        best, score = None, 0
        for vid, t, url in titles:
            ov = len(key & words(t))
            if ov > score:
                best, score = (t, url), ov
        rows.append((it.name, best[0] if best else "?", best[1] if best else "?", f"fuzzy:{score}"))
    out = ["# Source ↔ video matches\n", "| source | video | link | via |", "|---|---|---|---|"]
    out += [f"| {n} | {t} | {l} | {v} |" for n, t, l, v in rows]
    dest = ws / "reference" / "catalog.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"matched {len(rows)} sources -> {dest}")


def add_auth_options(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="let yt-dlp read YouTube cookies from a local browser (chrome, firefox, edge, ...)")
    g.add_argument("--cookies", metavar="FILE", help="Netscape cookies.txt file for yt-dlp")


def main():
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scaffold"); s.add_argument("--name", required=True); s.add_argument("--dir")
    s.add_argument("--channel"); s.add_argument("--author"); s.set_defaults(fn=cmd_scaffold)

    s = sub.add_parser("ingest"); s.add_argument("--workspace", required=True)
    s.add_argument("--channel"); s.add_argument("--count", type=int, default=15)
    s.add_argument("--videos"); s.add_argument("--frames", type=int, default=0)
    s.add_argument("--no-frames", action="store_true")
    s.add_argument("--force", action="store_true", help="re-download videos that already have a transcript")
    add_auth_options(s); s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("refresh"); s.add_argument("--workspace", required=True)
    s.add_argument("--count", type=int, default=30); s.add_argument("--frames", type=int, default=0)
    s.add_argument("--no-frames", action="store_true"); s.add_argument("--videos"); s.add_argument("--channel")
    s.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    add_auth_options(s); s.set_defaults(fn=cmd_refresh)

    s = sub.add_parser("status"); s.add_argument("--workspace", required=True); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("match"); s.add_argument("--workspace", required=True)
    s.add_argument("--sources", required=True); s.set_defaults(fn=cmd_match)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
