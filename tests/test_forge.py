"""Tests for scripts/forge.py. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
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
            forge.download_one(self.VIDEO, Path(d) / "abc", frames=0, auth=["--cookies-from-browser", "firefox"])

        cmd = run.call_args_list[0].args[0]
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "firefox")


def ingest_args(ws: Path, **overrides) -> argparse.Namespace:
    values = dict(workspace=str(ws), channel=None, count=15, videos=None, frames=0, no_frames=False,
                  force=False, cookies_from_browser=None, cookies=None)
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
