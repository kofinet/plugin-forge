#!/usr/bin/env python3
"""plugin-forge engine: turn a YouTube channel into the raw material for a Claude Code plugin.

Subcommands (deterministic steps; distill & build are LLM-driven and live in the commands):
  scaffold  --name NAME [--dir DIR]                 create an installable plugin skeleton
                                                    (DIR defaults to the current directory)
  ingest    --workspace DIR --channel URL --count N [--videos a,b] [--frames K] [--no-frames] [--force]
  refresh   --workspace DIR [--count N]             ingest only videos newer than the manifest
  status    --workspace DIR                         print the manifest summary
  match     --workspace DIR --sources DIR           map local code zips/folders to ingested videos
  deps      [--state-dir DIR] [--recheck]           check python/yt-dlp/ffmpeg, print install commands

ingest/refresh also take --cookies-from-browser BROWSER or --cookies FILE, passed straight to
yt-dlp, for when YouTube answers "Sign in to confirm you're not a bot".

Requires `yt-dlp` and (for frames) `ffmpeg`/`ffprobe` on PATH. Transcripts use free captions.
The workspace is the plugin dir; raw downloads + manifest live under <workspace>/.forge/.
"""
from __future__ import annotations
import argparse, json, os, platform, shutil, string, subprocess, sys, zipfile
from datetime import date
from pathlib import Path
from typing import Mapping

SLUG_CHARS = set(string.ascii_lowercase + string.digits + "-")
WORD_CHARS = set(string.ascii_lowercase + string.digits)
YOUTUBE_LINK_PREFIXES = ("https://youtu", "http://youtu")
COOKIES_HINT = ("YouTube may be asking to sign in: rerun with --cookies-from-browser <browser> "
                "or --cookies <cookies.txt>, or remember a browser for automatic retries with "
                "`forge.py cookies --state-dir <dir> --browser <browser>` (never commit cookie files).")
SETTINGS_FILE = "settings.json"
YT_DLP_BROWSERS = {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}

SETUP_HINT = "Run /plugin-forge:forge-setup (or `forge.py deps`) to check and install the dependencies."
MIN_PYTHON = (3, 9)
DEPS_FILE = "deps.json"
TOOLS = {  # tool -> what it is for
    "yt-dlp": "required: captions and channel listing",
    "ffmpeg": "optional: video frames (--frames)",
    "ffprobe": "optional: video frames (--frames)",
}
REQUIRED_TOOLS = ("yt-dlp",)
PACKAGE_MANAGERS = ("winget", "brew", "pipx", "apt-get", "dnf", "pacman", "zypper")
WINGET_IDS = {"yt-dlp": "yt-dlp.yt-dlp", "ffmpeg": "Gyan.FFmpeg"}
LINUX_FFMPEG = {
    "apt-get": "sudo apt-get install -y ffmpeg",
    "dnf": "sudo dnf install -y ffmpeg",
    "pacman": "sudo pacman -S --noconfirm ffmpeg",
    "zypper": "sudo zypper install -y ffmpeg",
}

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
    """Run a tool and decode its output as UTF-8 (not the Windows ANSI code page)."""
    try:
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        raise SystemExit(f"{cmd[0]} not found. {SETUP_HINT}") from None


def yt_dlp(*args: str) -> list[str]:
    """A yt-dlp command line; --encoding makes it print UTF-8 even into a Windows pipe."""
    return [find_tool("yt-dlp") or "yt-dlp", "--encoding", "utf-8", *args]


def tool_dirs(home: Path, env: Mapping[str, str], platform: str) -> list[Path]:
    """Usual install locations a fresh install may not have put on PATH yet
    (winget links, pipx / pip --user scripts, Homebrew, scoop, Chocolatey, snap)."""
    dirs = [home / ".local" / "bin"]
    if platform == "win32":
        local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        dirs += [local / "Microsoft" / "WinGet" / "Links", home / "scoop" / "shims",
                 Path(env.get("ProgramData") or "C:/ProgramData") / "chocolatey" / "bin"]
        dirs += sorted(roaming.glob("Python/Python3*/Scripts")) + sorted(local.glob("Programs/Python/Python3*/Scripts"))
    elif platform == "darwin":
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")] + sorted(home.glob("Library/Python/3.*/bin"))
    else:
        dirs += [Path("/usr/local/bin"), Path("/snap/bin"), Path("/home/linuxbrew/.linuxbrew/bin")]
    return dirs


def find_tool(name: str, extra_dirs: list[Path] | None = None) -> str | None:
    """Absolute path of a tool: from PATH, else from the usual install locations."""
    if extra_dirs is None:
        extra_dirs = tool_dirs(Path.home(), os.environ, sys.platform)
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(str(d) for d in extra_dirs))


def package_managers() -> dict[str, str]:
    """Package managers on this machine -> how to invoke them (quoted path when off PATH)."""
    found = {}
    for m in PACKAGE_MANAGERS:
        path = find_tool(m)
        if path:
            found[m] = m if shutil.which(m) else f'"{path}"'
    return found


def install_command(tool: str, platform: str, managers: Mapping[str, str], python: str) -> str | None:
    """Command that installs a tool with what this machine has, or None when it needs a manual install."""
    pkg = "ffmpeg" if tool == "ffprobe" else tool  # ffprobe ships with ffmpeg
    pip_user = f'"{python}" -m pip install --user {pkg}'
    if platform == "win32":
        if "winget" in managers:
            return f"{managers['winget']} install -e --id {WINGET_IDS[pkg]}"
        return pip_user if pkg == "yt-dlp" else None
    if "brew" in managers:  # macOS, or Homebrew on Linux
        return f"{managers['brew']} install {pkg}"
    if pkg == "yt-dlp":
        if "pipx" in managers:
            return f"{managers['pipx']} install yt-dlp"
        # distro yt-dlp packages are usually too old for YouTube; system pip is often locked (PEP 668)
        system = next((m for m in ("apt-get", "dnf") if m in managers), None)
        return f"sudo {system} install -y pipx && pipx install yt-dlp" if system else pip_user
    return next((cmd for m, cmd in LINUX_FFMPEG.items() if m in managers), None)


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


def read_cues(path: Path) -> list[tuple[int, list[str]]]:
    """(start seconds, cleaned non-empty lines) for each cue of a VTT file."""
    cues, start, lines = [], None, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cue_start = parse_cue_start(line)
        if cue_start is not None:
            if start is not None and lines:
                cues.append((start, lines))
            start, lines = cue_start, []
        elif line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:")):
            text = _clean(line)
            if text:
                lines.append(text)
    if start is not None and lines:
        cues.append((start, lines))
    return cues


def clean_vtt(path: Path) -> str:
    """Turn an en.vtt (manual or rolling auto-captions) into '[MM:SS] text' paragraphs (~15s)."""
    # Rolling auto-captions repeat the previous cue's line above the new words, so a line
    # already shown in the previous cue is dropped; this also drops repeated identical cues.
    cues, prev_lines = [], []
    for t, lines in read_cues(path):
        fresh = [ln for ln in lines if ln not in prev_lines]
        prev_lines = lines
        if fresh:
            cues.append((t, " ".join(fresh)))
    # group into ~15s paragraphs
    paras, cs, cur = [], None, []
    for t, x in cues:
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


def is_sign_in_check(stderr: str) -> bool:
    """YouTube's "Sign in to confirm you're not a bot" refusal."""
    return "Sign in to confirm" in stderr and "not a bot" in stderr


class YouTubeAuth:
    """yt-dlp auth flags for one run (never logged). Without explicit flags, the first
    "not a bot" sign-in check switches the rest of the run to the remembered browser's cookies."""

    def __init__(self, args: list[str] | None = None, fallback: list[str] | None = None):
        self.args = list(args or [])
        self.fallback = list(fallback or [])

    def run(self, *args: str) -> subprocess.CompletedProcess:
        cp = run(yt_dlp(*self.args, *args))
        if cp.returncode != 0 and not self.args and self.fallback and is_sign_in_check(cp.stderr):
            print(f"    YouTube asked to sign in; retrying with cookies from {self.fallback[-1]}", file=sys.stderr)
            self.args = self.fallback
            cp = run(yt_dlp(*self.args, *args))
        return cp


def load_settings(state_dir: str | None) -> dict:
    path = Path(state_dir) / SETTINGS_FILE if state_dir else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}


def youtube_auth(a) -> YouTubeAuth:
    """Explicit --cookies* flags, else the remembered browser as the sign-in fallback."""
    browser = load_settings(getattr(a, "state_dir", None)).get("cookiesFromBrowser")
    return YouTubeAuth(auth_args(a), ["--cookies-from-browser", browser] if browser else [])


def newest(channel: str, count: int | None, auth: YouTubeAuth | None = None) -> list[dict]:
    args = ["--flat-playlist", "--no-warnings", "--print", "%(id)s\t%(title)s"]
    if count:
        args += ["--playlist-end", str(count)]
    url = channel if "/videos" in channel or "list=" in channel else channel.rstrip("/") + "/videos"
    cp = (auth or YouTubeAuth()).run(*args, url)
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
    cp = run([find_tool("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(video)])
    try:
        return float(cp.stdout.strip())
    except ValueError:
        return 0.0


def download_one(vid: dict, vdir: Path, frames: int, auth: YouTubeAuth | None = None) -> dict:
    auth = auth or YouTubeAuth()
    vdir.mkdir(parents=True, exist_ok=True)
    rec = {**vid, "transcript": False, "frames": 0}
    # 1) captions (no video download) — fast & free
    cp = auth.run("--skip-download", "--write-subs", "--write-auto-subs",
                  "--sub-langs", "en,en-orig,en.*", "--sub-format", "vtt", "--convert-subs", "vtt",
                  "--no-warnings", "-o", str(vdir / "video.%(ext)s"), vid["url"])
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
        ffmpeg = find_tool("ffmpeg")
        cp = auth.run("-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                      *(["--ffmpeg-location", ffmpeg] if ffmpeg else []),
                      "--no-warnings", "-o", str(vdir / "src.%(ext)s"), vid["url"])
        src = next((p for p in vdir.glob("src.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm")), None)
        if src:
            dur = ffprobe_duration(src) or 600
            fps = max(0.05, min(1.0, frames / dur))
            fdir = vdir / "frames"
            fdir.mkdir(exist_ok=True)
            run([ffmpeg or "ffmpeg", "-y", "-i", str(src), "-vf", f"fps={fps:.4f},scale=512:-1",
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
    auth = youtube_auth(a)
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
        print(f"[{i}/{len(todo)}] {vid['id']} {vid['title'][:60]}", flush=True)
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
    fresh = [v for v in newest(m["channel"], a.count, youtube_auth(a)) if v["id"] not in have]
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


def saved_deps_ok(state: Path) -> str | None:
    """Date of a saved successful check whose required tools are all still there, else None."""
    if not state.exists():
        return None
    saved = json.loads(state.read_text(encoding="utf-8"))
    tools = saved.get("tools", {})
    if all(tools.get(t) and Path(tools[t]).exists() for t in REQUIRED_TOOLS):
        return saved.get("checkedAt", "?")
    return None


def cmd_deps(a):
    state = Path(a.state_dir) / DEPS_FILE if a.state_dir else None
    if state and not a.recheck:
        checked = saved_deps_ok(state)
        if checked:
            print(f"dependencies ok (checked {checked}); --recheck to check again")
            return
    python_ok = sys.version_info >= MIN_PYTHON
    tools = {t: find_tool(t) for t in TOOLS}
    managers = package_managers() if not all(tools.values()) else {}
    print(f"platform: {sys.platform}   python: {platform.python_version()} ({sys.executable})"
          + ("" if python_ok else f"   ! needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+"))
    for t, purpose in TOOLS.items():
        path = tools[t]
        if path:
            note = "" if shutil.which(t) else "   (not on PATH; forge uses this path directly)"
            print(f"  [ok]      {t:<8} {path}{note}")
        else:
            cmd = install_command(t, sys.platform, managers, sys.executable)
            print(f"  [missing] {t:<8} {purpose}; install: {cmd or 'no supported package manager found, see README'}")
    print(f"cookies fallback: {load_settings(a.state_dir).get('cookiesFromBrowser') or 'off'}")
    if not (python_ok and all(tools[t] for t in REQUIRED_TOOLS)):
        raise SystemExit("missing required dependencies")
    if state:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"checkedAt": date.today().isoformat(), "python": sys.executable,
                                     "tools": tools}, indent=1), encoding="utf-8")
    print("ready")


def cmd_cookies(a):
    settings = load_settings(a.state_dir)
    if a.browser:
        name = a.browser.split(":")[0].split("+")[0]  # yt-dlp syntax: BROWSER[+KEYRING][:PROFILE]
        if name not in YT_DLP_BROWSERS:
            raise SystemExit(f"unknown browser {name!r}; one of: {', '.join(sorted(YT_DLP_BROWSERS))}")
        settings["cookiesFromBrowser"] = a.browser
    elif a.off:
        settings.pop("cookiesFromBrowser", None)
    if a.browser or a.off:
        path = Path(a.state_dir) / SETTINGS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    print(f"cookies fallback: {settings.get('cookiesFromBrowser') or 'off'}")


def add_auth_options(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="let yt-dlp read YouTube cookies from a local browser (chrome, firefox, edge, ...)")
    g.add_argument("--cookies", metavar="FILE", help="Netscape cookies.txt file for yt-dlp")
    p.add_argument("--state-dir", help="plugin data dir; its remembered browser is used when YouTube asks to sign in")


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

    s = sub.add_parser("deps", help="check python/yt-dlp/ffmpeg and print install commands for what is missing")
    s.add_argument("--state-dir", help="where to remember a successful check (skips later checks)")
    s.add_argument("--recheck", action="store_true", help="ignore the remembered check")
    s.set_defaults(fn=cmd_deps)

    s = sub.add_parser("cookies", help="remember (or forget) the browser whose cookies are used when YouTube asks to sign in")
    s.add_argument("--state-dir", required=True)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--browser", help="firefox, chrome, edge, ... optionally with a profile: firefox:PROFILE")
    g.add_argument("--off", action="store_true")
    s.set_defaults(fn=cmd_cookies)

    # Titles and errors may hold any language; Windows pipes default to the ANSI code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
