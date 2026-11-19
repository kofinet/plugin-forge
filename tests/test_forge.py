"""Tests for scripts/forge.py. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

FORGE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "forge.py"
sys.path.insert(0, str(FORGE_SCRIPT.parent))
import forge  # noqa: E402


class QuietTestCase(unittest.TestCase):
    """Swallows the progress and error lines the commands print, so the test run output stays readable."""

    def setUp(self):
        for quiet in (contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            quiet.__enter__()
            self.addCleanup(quiet.__exit__, None, None, None)


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


SAMPLE_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:04.000
Hello <c>and</c>&nbsp;welcome

00:00:04.000 --> 00:00:06.000
Hello <c>and</c>&nbsp;welcome

00:00:06.000 --> 00:00:09.000
to   the
channel

00:00:17.500 --> 00:00:20.000
<00:00:17.900>Second paragraph

01:00:05.000 --> 01:00:07.000
An hour in
"""


# Shape of YouTube's automatic captions: each cue repeats the previous line above the new words,
# and a 10 ms cue in between holds only the finished line.
ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.200 --> 00:00:02.090 align:start position:0%

First<00:00:00.300><c> line</c><00:00:00.500><c> of</c><00:00:00.600><c> words</c>

00:00:02.090 --> 00:00:02.100 align:start position:0%
First line of words


00:00:02.100 --> 00:00:04.390 align:start position:0%
First line of words
second<00:00:02.700><c> line</c><00:00:02.900><c> here</c>

00:00:04.390 --> 00:00:04.400 align:start position:0%
second line here


00:00:04.400 --> 00:00:07.190 align:start position:0%
second line here
third<00:00:04.700><c> line</c>
"""


class CleanVttTests(QuietTestCase):
    def test_clean_vtt_groups_cues_into_timestamped_paragraphs(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "video.en.vtt"
            path.write_text(SAMPLE_VTT, encoding="utf-8")

            text = forge.clean_vtt(path)

        self.assertEqual(
            text,
            "[00:01] Hello and welcome to the channel\n"
            "[00:17] Second paragraph\n"
            "[60:05] An hour in",
        )

    def test_clean_vtt_keeps_each_line_of_rolling_auto_captions_once(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "video.en.vtt"
            path.write_text(ROLLING_VTT, encoding="utf-8")

            text = forge.clean_vtt(path)

        self.assertEqual(text, "[00:00] First line of words second line here third line")

    def test_clean_strips_tags_entities_and_extra_whitespace(self):
        self.assertEqual(forge._clean("  <c.colorE5E5E5>a</c>&nbsp;b    c  "), "a b c")


class ScaffoldTests(QuietTestCase):
    def scaffold(self, parent: Path, name: str) -> Path:
        forge.cmd_scaffold(argparse.Namespace(name=name, dir=str(parent), channel="https://www.youtube.com/@x", author=None))
        return parent / name

    def test_scaffold_writes_manifests_with_slug(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.scaffold(Path(d), "My Cool Plugin!")

            plugin = json.loads((ws / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            market = json.loads((ws / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
            manifest = json.loads((ws / ".forge" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(plugin["name"], "my-cool-plugin")
        self.assertEqual(market["name"], "my-cool-plugin-marketplace")
        self.assertEqual(manifest["channel"], "https://www.youtube.com/@x")

    def test_scaffold_gitignores_forge_workdir(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.scaffold(Path(d), "demo")

            lines = (ws / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn(".forge/", lines)

    def test_scaffold_writes_readme(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.scaffold(Path(d), "demo")

            readme = (ws / "README.md").read_text(encoding="utf-8")

        self.assertTrue(readme.startswith("# demo\n"))

    def test_scaffold_without_dir_creates_plugin_in_current_directory(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = Path(d).resolve()
            with mock.patch.object(forge.Path, "cwd", return_value=cwd):
                forge.cmd_scaffold(argparse.Namespace(name="demo", dir=None, channel=None, author=None))

            created = (cwd / "demo" / ".claude-plugin" / "plugin.json").exists()

        self.assertTrue(created)

    def test_scaffold_rejects_name_without_letters_or_digits(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                self.scaffold(Path(d), "!!!")


class DownloadTests(QuietTestCase):
    VIDEO = {"id": "abc", "title": "T", "url": "https://www.youtube.com/watch?v=abc"}

    def test_download_one_reports_yt_dlp_error(self):
        stderr = "WARNING: something\nERROR: [youtube] abc: Sign in to confirm you're not a bot.\n"
        with tempfile.TemporaryDirectory() as d, mock.patch.object(forge, "run", return_value=completed(1, stderr=stderr)):
            rec = forge.download_one(self.VIDEO, Path(d) / "abc", frames=0)

        self.assertFalse(rec["transcript"])
        self.assertEqual(rec["error"], "ERROR: [youtube] abc: Sign in to confirm you're not a bot.")

    def test_download_one_reports_missing_captions(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(forge, "run", return_value=completed(0)):
            rec = forge.download_one(self.VIDEO, Path(d) / "abc", frames=0)

        self.assertFalse(rec["transcript"])
        self.assertEqual(rec["error"], "no English captions available")

    def test_download_one_passes_auth_args_to_yt_dlp(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(forge, "run", return_value=completed(0)) as run:
            forge.download_one(self.VIDEO, Path(d) / "abc", frames=0,
                               auth=forge.YouTubeAuth(["--cookies-from-browser", "firefox"]))

        cmd = run.call_args_list[0].args[0]
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "firefox")

    def test_download_one_asks_yt_dlp_for_utf8_output(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(forge, "run", return_value=completed(0)) as run:
            forge.download_one(self.VIDEO, Path(d) / "abc", frames=0)

        cmd = run.call_args_list[0].args[0]
        self.assertEqual(cmd[cmd.index("--encoding") + 1], "utf-8")

    def test_newest_asks_yt_dlp_for_utf8_output(self):
        with mock.patch.object(forge, "run", return_value=completed(0, stdout="abc\tZażółć gęślą jaźń\n")) as run:
            videos = forge.newest("https://www.youtube.com/@x", 1)

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--encoding") + 1], "utf-8")
        self.assertEqual(videos[0]["title"], "Zażółć gęślą jaźń")


NON_ASCII = "Zażółć gęślą jaźń – you’re"


class EncodingTests(QuietTestCase):
    def test_run_decodes_tool_output_as_utf8(self):
        script = f"import sys; sys.stdout.buffer.write({NON_ASCII!r}.encode('utf-8'))"

        cp = forge.run([sys.executable, "-c", script])

        self.assertEqual(cp.stdout, NON_ASCII)

    def test_status_prints_non_ascii_titles_as_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            forge.save_manifest(Path(d), {"pluginName": "p", "channel": None, "videos": [
                {"id": "abc", "title": NON_ASCII, "url": "u", "transcript": True, "frames": 0}]})
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}

            cp = subprocess.run([sys.executable, str(FORGE_SCRIPT), "status", "--workspace", d],
                                capture_output=True, env=env)

        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(NON_ASCII.encode("utf-8"), cp.stdout)

    def test_run_reports_missing_tool_with_setup_hint(self):
        with self.assertRaises(SystemExit) as ctx:
            forge.run(["plugin-forge-no-such-tool"])

        self.assertEqual(ctx.exception.code, f"plugin-forge-no-such-tool not found. {forge.SETUP_HINT}")


def ingest_args(ws: Path, **overrides) -> argparse.Namespace:
    values = dict(workspace=str(ws), channel=None, count=15, videos=None, frames=0, no_frames=False,
                  force=False, cookies_from_browser=None, cookies=None, state_dir=None)
    values.update(overrides)
    return argparse.Namespace(**values)


class IngestTests(QuietTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        forge.save_manifest(self.ws, {"pluginName": "p", "channel": "https://www.youtube.com/@x", "videos": [
            {"id": "old", "title": "Old", "url": "u", "transcript": True, "frames": 0},
        ]})

    def tearDown(self):
        self.tmp.cleanup()

    def fake_download(self, vid, vdir, frames, auth=None):
        return {**vid, "transcript": True, "frames": 0}

    def test_ingest_skips_videos_that_already_have_a_transcript(self):
        listed = [{"id": "new", "title": "New", "url": "u2"}, {"id": "old", "title": "Old", "url": "u"}]
        with mock.patch.object(forge, "newest", return_value=listed), \
                mock.patch.object(forge, "download_one", side_effect=self.fake_download) as dl:
            forge.cmd_ingest(ingest_args(self.ws))

        self.assertEqual([c.args[0]["id"] for c in dl.call_args_list], ["new"])

    def test_ingest_force_downloads_already_ingested_videos(self):
        listed = [{"id": "old", "title": "Old", "url": "u"}]
        with mock.patch.object(forge, "newest", return_value=listed), \
                mock.patch.object(forge, "download_one", side_effect=self.fake_download) as dl:
            forge.cmd_ingest(ingest_args(self.ws, force=True))

        self.assertEqual([c.args[0]["id"] for c in dl.call_args_list], ["old"])

    def test_ingest_fails_when_no_transcript_was_captured(self):
        listed = [{"id": "new", "title": "New", "url": "u2"}]
        failed = {"id": "new", "title": "New", "url": "u2", "transcript": False, "frames": 0, "error": "ERROR: boom"}
        with mock.patch.object(forge, "newest", return_value=listed), \
                mock.patch.object(forge, "download_one", return_value=failed):
            with self.assertRaises(SystemExit) as ctx:
                forge.cmd_ingest(ingest_args(self.ws))

        self.assertNotEqual(ctx.exception.code, 0)
        saved = forge.load_manifest(self.ws)
        self.assertEqual([v["id"] for v in saved["videos"]], ["old", "new"])


def make_executable(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + (".exe" if os.name == "nt" else ""))
    path.write_bytes(b"")
    path.chmod(0o755)
    return path


class ToolLookupTests(QuietTestCase):
    def test_find_tool_uses_usual_install_dir_when_tool_is_not_on_path(self):
        with tempfile.TemporaryDirectory() as d:
            tool = make_executable(Path(d) / ".local" / "bin", "plugin-forge-fake-tool")

            found = forge.find_tool("plugin-forge-fake-tool", [tool.parent])

        self.assertEqual(os.path.normcase(found), os.path.normcase(str(tool)))

    def test_find_tool_returns_none_for_unknown_tool(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(forge.find_tool("plugin-forge-no-such-tool", [Path(d)]))

    def test_tool_dirs_include_winget_links_on_windows(self):
        dirs = forge.tool_dirs(Path("home"), {"LOCALAPPDATA": "local"}, "win32")

        self.assertIn(Path("local") / "Microsoft" / "WinGet" / "Links", dirs)

    def test_tool_dirs_include_homebrew_on_macos(self):
        dirs = forge.tool_dirs(Path("home"), {}, "darwin")

        self.assertIn(Path("/opt/homebrew/bin"), dirs)

    def test_tool_dirs_include_pipx_bin_on_linux(self):
        dirs = forge.tool_dirs(Path("home"), {}, "linux")

        self.assertIn(Path("home") / ".local" / "bin", dirs)


SIGN_IN = completed(1, stderr="ERROR: [youtube] abc: Sign in to confirm you’re not a bot. This helps protect our community.\n")
FIREFOX = ["--cookies-from-browser", "firefox"]


def uses_cookies(call) -> bool:
    return "--cookies-from-browser" in call.args[0] or "--cookies" in call.args[0]


class SignInFallbackTests(QuietTestCase):
    def test_retries_with_remembered_browser_cookies_when_youtube_asks_to_sign_in(self):
        auth = forge.YouTubeAuth([], FIREFOX)
        with mock.patch.object(forge, "run", side_effect=[SIGN_IN, completed(0)]) as run:
            cp = auth.run("--skip-download", "https://www.youtube.com/watch?v=abc")

        self.assertEqual(cp.returncode, 0)
        self.assertEqual([uses_cookies(c) for c in run.call_args_list], [False, True])

    def test_keeps_using_cookies_for_the_rest_of_the_run(self):
        auth = forge.YouTubeAuth([], FIREFOX)
        with mock.patch.object(forge, "run", side_effect=[SIGN_IN, completed(0), completed(0)]) as run:
            auth.run("--skip-download", "https://www.youtube.com/watch?v=abc")
            auth.run("--skip-download", "https://www.youtube.com/watch?v=def")

        self.assertEqual([uses_cookies(c) for c in run.call_args_list], [False, True, True])

    def test_other_errors_are_not_retried(self):
        auth = forge.YouTubeAuth([], FIREFOX)
        with mock.patch.object(forge, "run", return_value=completed(1, stderr="ERROR: Video unavailable")) as run:
            auth.run("--skip-download", "https://www.youtube.com/watch?v=abc")

        self.assertEqual(run.call_count, 1)

    def test_without_remembered_browser_sign_in_check_is_not_retried(self):
        auth = forge.YouTubeAuth([], [])
        with mock.patch.object(forge, "run", return_value=SIGN_IN) as run:
            auth.run("--skip-download", "https://www.youtube.com/watch?v=abc")

        self.assertEqual(run.call_count, 1)

    def test_explicit_cookies_are_not_replaced_by_remembered_browser(self):
        auth = forge.YouTubeAuth(["--cookies", "cookies.txt"], FIREFOX)
        with mock.patch.object(forge, "run", return_value=SIGN_IN) as run:
            auth.run("--skip-download", "https://www.youtube.com/watch?v=abc")

        self.assertEqual(run.call_count, 1)


def cookies_args(state_dir: Path, browser=None, off=False) -> argparse.Namespace:
    return argparse.Namespace(state_dir=str(state_dir), browser=browser, off=off)


class CookiesSettingTests(QuietTestCase):
    def test_cookies_remembers_browser_for_later_runs(self):
        with tempfile.TemporaryDirectory() as d:
            forge.cmd_cookies(cookies_args(Path(d), browser="firefox"))

            auth = forge.youtube_auth(ingest_args(Path(d), state_dir=d))

        self.assertEqual((auth.args, auth.fallback), ([], FIREFOX))

    def test_cookies_accepts_a_browser_profile(self):
        with tempfile.TemporaryDirectory() as d:
            forge.cmd_cookies(cookies_args(Path(d), browser="firefox:youtube-forge"))

            auth = forge.youtube_auth(ingest_args(Path(d), state_dir=d))

        self.assertEqual(auth.fallback, ["--cookies-from-browser", "firefox:youtube-forge"])

    def test_cookies_off_forgets_browser(self):
        with tempfile.TemporaryDirectory() as d:
            forge.cmd_cookies(cookies_args(Path(d), browser="firefox"))
            forge.cmd_cookies(cookies_args(Path(d), off=True))

            auth = forge.youtube_auth(ingest_args(Path(d), state_dir=d))

        self.assertEqual(auth.fallback, [])

    def test_cookies_rejects_unknown_browser(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                forge.cmd_cookies(cookies_args(Path(d), browser="netscape"))

    def test_explicit_cookie_flags_are_used_from_the_start(self):
        with tempfile.TemporaryDirectory() as d:
            forge.cmd_cookies(cookies_args(Path(d), browser="firefox"))

            auth = forge.youtube_auth(ingest_args(Path(d), state_dir=d, cookies_from_browser="chrome"))

        self.assertEqual(auth.args, ["--cookies-from-browser", "chrome"])


class InstallCommandTests(unittest.TestCase):
    def test_windows_uses_winget(self):
        self.assertEqual(forge.install_command("yt-dlp", "win32", {"winget": "winget"}, "py"),
                         "winget install -e --id yt-dlp.yt-dlp")

    def test_windows_without_winget_needs_manual_ffmpeg(self):
        self.assertIsNone(forge.install_command("ffmpeg", "win32", {}, "py"))

    def test_macos_installs_ffprobe_through_ffmpeg_formula(self):
        self.assertEqual(forge.install_command("ffprobe", "darwin", {"brew": "brew"}, "python3"), "brew install ffmpeg")

    def test_linux_installs_yt_dlp_with_pipx_from_the_distro(self):
        self.assertEqual(forge.install_command("yt-dlp", "linux", {"apt-get": "apt-get"}, "python3"),
                         "sudo apt-get install -y pipx && pipx install yt-dlp")

    def test_linux_installs_ffmpeg_with_the_distro_package_manager(self):
        self.assertEqual(forge.install_command("ffmpeg", "linux", {"dnf": "dnf"}, "python3"),
                         "sudo dnf install -y ffmpeg")

    def test_linux_without_package_manager_falls_back_to_pip_user(self):
        self.assertEqual(forge.install_command("yt-dlp", "linux", {}, "/usr/bin/python3"),
                         '"/usr/bin/python3" -m pip install --user yt-dlp')


class DepsTests(QuietTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.yt_dlp = make_executable(Path(self.tmp.name) / "bin", "yt-dlp")

    def tearDown(self):
        self.tmp.cleanup()

    def deps(self, found: dict, recheck: bool = False):
        with mock.patch.object(forge, "find_tool", side_effect=lambda name, extra_dirs=None: found.get(name)) as lookup, \
                mock.patch.object(forge, "package_managers", return_value={}):
            forge.cmd_deps(argparse.Namespace(state_dir=str(self.state_dir), recheck=recheck))
        return lookup

    def test_deps_fails_and_remembers_nothing_when_yt_dlp_is_missing(self):
        with self.assertRaises(SystemExit) as ctx:
            self.deps({})

        self.assertEqual(ctx.exception.code, "missing required dependencies")
        self.assertFalse((self.state_dir / forge.DEPS_FILE).exists())

    def test_deps_remembers_found_tools(self):
        self.deps({"yt-dlp": str(self.yt_dlp)})

        saved = json.loads((self.state_dir / forge.DEPS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["tools"], {"yt-dlp": str(self.yt_dlp), "ffmpeg": None, "ffprobe": None})

    def test_deps_skips_the_check_after_a_successful_one(self):
        self.deps({"yt-dlp": str(self.yt_dlp)})

        lookup = self.deps({"yt-dlp": str(self.yt_dlp)})

        lookup.assert_not_called()

    def test_deps_checks_again_when_a_remembered_tool_is_gone(self):
        self.deps({"yt-dlp": str(self.yt_dlp)})
        self.yt_dlp.unlink()

        with self.assertRaises(SystemExit):
            self.deps({})

    def test_deps_recheck_ignores_the_remembered_check(self):
        self.deps({"yt-dlp": str(self.yt_dlp)})

        lookup = self.deps({"yt-dlp": str(self.yt_dlp)}, recheck=True)

        lookup.assert_called()


class MatchTests(QuietTestCase):
    def test_match_prefers_youtube_link_from_zip_readme(self):
        with tempfile.TemporaryDirectory() as d:
            ws, src = Path(d) / "ws", Path(d) / "src"
            src.mkdir()
            forge.save_manifest(ws, {"pluginName": "p", "channel": None, "videos": []})
            with zipfile.ZipFile(src / "code-demo.zip", "w") as z:
                z.writestr("demo/Readme.md", "See [Great Video](https://youtu.be/xyz) for details.\n")

            forge.cmd_match(argparse.Namespace(workspace=str(ws), sources=str(src)))

            catalog = (ws / "reference" / "catalog.md").read_text(encoding="utf-8").splitlines()

        self.assertIn("| code-demo.zip | Great Video | https://youtu.be/xyz | readme |", catalog)

    def test_match_falls_back_to_title_word_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            ws, src = Path(d) / "ws", Path(d) / "src"
            (src / "code-records-in-csharp").mkdir(parents=True)
            forge.save_manifest(ws, {"pluginName": "p", "channel": None, "videos": [
                {"id": "a", "title": "Records in C#: the good parts", "url": "https://www.youtube.com/watch?v=a"},
                {"id": "b", "title": "Async streams", "url": "https://www.youtube.com/watch?v=b"},
            ]})

            forge.cmd_match(argparse.Namespace(workspace=str(ws), sources=str(src)))

            catalog = (ws / "reference" / "catalog.md").read_text(encoding="utf-8").splitlines()

        self.assertIn("| code-records-in-csharp | Records in C#: the good parts | https://www.youtube.com/watch?v=a | fuzzy:2 |", catalog)


if __name__ == "__main__":
    unittest.main()
