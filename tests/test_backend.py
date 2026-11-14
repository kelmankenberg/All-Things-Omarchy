import importlib.util
import io
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


BACKEND_PATH = Path(__file__).resolve().parents[1] / "Backend.py"
SPEC = importlib.util.spec_from_file_location("all_things_backend", BACKEND_PATH)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)

TEST_DIRECTORY = BACKEND_PATH.parent / ("tests/.backend-work-" + str(os.getpid()))
ORIGINAL_TEMPDIR = tempfile.tempdir
TEST_ENVIRONMENT = patch.dict(os.environ, {"XDG_STATE_HOME": str(TEST_DIRECTORY / "xdg-state"),
                                          "PYTHONDONTWRITEBYTECODE": "1"})


def setUpModule():
    TEST_DIRECTORY.mkdir(mode=0o700)
    tempfile.tempdir = str(TEST_DIRECTORY)
    TEST_ENVIRONMENT.start()


def tearDownModule():
    tempfile.tempdir = ORIGINAL_TEMPDIR
    TEST_ENVIRONMENT.stop()
    shutil.rmtree(TEST_DIRECTORY)


class TextTests(unittest.TestCase):
    def test_clean_text_removes_markup_and_control_characters(self):
        self.assertEqual(
            "Omarchy updates",
            backend.clean_text("<b>Omarchy</b> updates\u0000"),
        )

    def test_clean_text_bounds_untrusted_text(self):
        self.assertEqual("safe", backend.clean_text("safe" + "x" * 100, 4))


class CatalogTests(unittest.TestCase):
    def test_public_version_comes_from_installed_manifest_and_rejects_missing_version(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            with patch.object(backend, "__file__", str(Path(directory) / "Backend.py")):
                manifest.write_text(json.dumps({"version": "0.2.0+test"}), encoding="utf-8")
                self.assertEqual("0.2.0+test",
                                 backend.public_state(backend.empty_state())["pluginVersion"])
                manifest.write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "valid version"):
                    backend.public_state(backend.empty_state())

    def test_update_launcher_is_detached_interactive_and_reports_startup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            command = path / "omarchy"
            args_path = path / "args.json"
            command.write_text("""#!/usr/bin/python3
import json
import os
import pathlib
import sys
pathlib.Path(os.environ["UPDATE_TEST_ARGS"]).write_text(json.dumps(sys.argv[1:]))
print("launcher diagnostic", file=sys.stderr)
sys.exit(int(os.environ.get("UPDATE_TEST_EXIT", "0")))
""", encoding="utf-8")
            command.chmod(0o700)
            env = {"PATH": directory + os.pathsep + os.environ.get("PATH", ""),
                   "UPDATE_TEST_ARGS": str(args_path), "UPDATE_TEST_EXIT": "0"}
            with patch.dict(os.environ, env), \
                    patch.object(backend, "state_path", return_value=path / "state.json"), \
                    patch.object(backend.subprocess, "Popen", wraps=subprocess.Popen) as popen:
                result = backend.launch_update()
                self.assertTrue(result["requested"])
                self.assertEqual(str(path / "update-launch.log"), result["log"])
                self.assertTrue(popen.call_args.kwargs["start_new_session"])
                self.assertEqual(["launch", "floating", "terminal", "with", "presentation", "omarchy-update"],
                                 json.loads(args_path.read_text(encoding="utf-8")))
                self.assertEqual(0o600, Path(result["log"]).stat().st_mode & 0o777)
                self.assertIn("launcher diagnostic", Path(result["log"]).read_text(encoding="utf-8"))
                with patch.dict(os.environ, {"UPDATE_TEST_EXIT": "7"}):
                    with self.assertRaisesRegex(RuntimeError, "launcher diagnostic"):
                        backend.launch_update()

    def test_update_launcher_returns_without_waiting_for_the_update(self):
        process = SimpleNamespace(wait=Mock(side_effect=subprocess.TimeoutExpired("omarchy", 1)))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"), \
                patch.object(backend.subprocess, "Popen", return_value=process) as popen:
            response = backend.launch_update()
        self.assertTrue(response["requested"])
        self.assertEqual(["omarchy", "launch", "floating", "terminal", "with", "presentation", "omarchy-update"],
                         popen.call_args.args[0])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_theme_preview_prefers_local_images_and_rejects_external_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            user_theme = home / ".config" / "omarchy" / "themes" / "tokyo-night"
            stock_theme = base / "omarchy" / "themes" / "tokyo-night"
            user_theme.mkdir(parents=True)
            stock_theme.mkdir(parents=True)
            stock_preview = stock_theme / "preview.png"
            stock_preview.write_bytes(ThumbnailBoundaryTests.png())
            local_preview = user_theme / "preview.png"
            local_preview.write_bytes(ThumbnailBoundaryTests.png())
            with patch.object(backend.Path, "home", return_value=home), \
                    patch.dict(os.environ, {"OMARCHY_PATH": str(base / "omarchy")}):
                self.assertEqual(local_preview.as_uri(), backend.theme_preview("Tokyo Night"))
                local_preview.unlink()
                outside = base / "outside.png"
                outside.write_bytes(ThumbnailBoundaryTests.png())
                local_preview.symlink_to(outside)
                background = user_theme / "backgrounds" / "background.jpg"
                background.parent.mkdir()
                background.write_bytes(ThumbnailBoundaryTests.png())
                self.assertEqual(background.as_uri(), backend.theme_preview("Tokyo Night"))
                background.unlink()
                self.assertEqual(stock_preview.as_uri(), backend.theme_preview("Tokyo Night"))
                stock_preview.unlink()
                self.assertEqual("", backend.theme_preview("Tokyo Night"))
                self.assertEqual("", backend.theme_preview("../outside"))

    def test_theme_status_lists_installed_names_and_exposes_errors(self):
        current = SimpleNamespace(returncode=0, stdout="Current Theme\n", stderr="")
        listing = SimpleNamespace(returncode=0, stdout="Current Theme\nTokyo Night\n", stderr="")
        with patch.object(backend, "system_command", side_effect=[(current, ""), (listing, "")]), \
                patch.object(backend, "theme_preview", side_effect=lambda name, errors=None: "file:///preview.png"
                             if name == "Tokyo Night" else ""):
            response = backend.theme_status()
        self.assertEqual("Current Theme", response["current"]["value"])
        self.assertEqual(["Current Theme", "Tokyo Night"], response["themes"])
        self.assertEqual({"Tokyo Night": "file:///preview.png"}, response["previews"])
        self.assertEqual("", response["listError"])

        listing = SimpleNamespace(returncode=0, stdout="Current Theme\n../unsafe\n", stderr="")
        with patch.object(backend, "system_command", side_effect=[(current, ""), (listing, "")]):
            response = backend.theme_status()
        self.assertEqual(["Current Theme"], response["themes"])
        self.assertIn("safely", response["listError"])
        with patch.object(backend, "system_command", side_effect=[(None, "no current"), (None, "no list")]):
            response = backend.theme_status()
        self.assertEqual("no current", response["current"]["error"])
        self.assertEqual("no list", response["listError"])

    def test_theme_selection_checks_current_list_and_runs_without_shell_interpolation(self):
        before = {"current": {"value": "Current", "error": ""},
                  "themes": ["Current", "Tokyo Night"], "listError": "", "actionError": "", "warning": ""}
        after = dict(before, current={"value": "Tokyo Night", "error": ""})
        success = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(backend, "theme_status", side_effect=[before, after]), \
                patch.object(backend, "system_command", return_value=(success, "")) as run:
            response = backend.set_theme("Tokyo Night")
        run.assert_called_once_with(["omarchy", "theme", "set", "Tokyo Night"], 180)
        self.assertEqual("Tokyo Night", response["current"]["value"])
        self.assertEqual("", response["actionError"])

        with patch.object(backend, "theme_status", return_value=before), \
                patch.object(backend, "system_command") as run:
            self.assertEqual(before, backend.set_theme("Current"))
            with self.assertRaisesRegex(ValueError, "no longer available"):
                backend.set_theme("Not Installed")
        run.assert_not_called()

    def test_theme_selection_reports_failures_and_resynchronizes_current_theme(self):
        state = {"current": {"value": "Current", "error": ""},
                 "themes": ["Current", "Tokyo Night"], "listError": "", "actionError": "", "warning": ""}
        failed = SimpleNamespace(returncode=1, stdout="Theme not found", stderr="")
        with patch.object(backend, "theme_status", side_effect=[dict(state), dict(state)]), \
                patch.object(backend, "system_command", return_value=(failed, "")):
            response = backend.set_theme("Tokyo Night")
        self.assertEqual("Current", response["current"]["value"])
        self.assertEqual("Theme not found", response["actionError"])
        with patch.object(backend, "theme_status", side_effect=[dict(state), dict(state)]), \
                patch.object(backend, "system_command", return_value=(None, "The command timed out")):
            response = backend.set_theme("Tokyo Night")
        self.assertIn("timed out", response["actionError"])
        self.assertIn("Check the current theme", response["actionError"])

    def test_theme_set_helper_runs_against_installed_theme_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "current").write_text("Current", encoding="utf-8")
            command = path / "omarchy"
            command.write_text("""#!/usr/bin/python3
import os
import pathlib
import sys
current = pathlib.Path(os.environ["THEME_TEST_CURRENT"])
if sys.argv[1:] == ["theme", "current"]:
    print(current.read_text())
elif sys.argv[1:] == ["theme", "list"]:
    print("Current\\nTokyo Night")
elif sys.argv[1:3] == ["theme", "set"] and len(sys.argv) == 4:
    current.write_text(sys.argv[3])
else:
    sys.exit(1)
""", encoding="utf-8")
            command.chmod(0o700)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ.get("PATH", ""),
                       THEME_TEST_CURRENT=str(path / "current"), PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([sys.executable, str(BACKEND_PATH), "theme-set", "Tokyo Night"],
                                    env=env, capture_output=True, text=True, timeout=15, check=True)
            response = json.loads(result.stdout)
            self.assertEqual("Tokyo Night", response["current"]["value"])
            self.assertEqual("Tokyo Night", (path / "current").read_text(encoding="utf-8"))
            self.assertEqual("", response["actionError"])

    def test_community_resources_are_bounded_searchable_and_reject_unsafe_links(self):
        rows = backend.normalize_community([
            {"id": "1", "name": "Older", "link": "https://example.org/a",
             "category": "Tools", "tags": ["searchable", "theme"]},
            {"id": "2", "name": "Newer", "link": "https://github.com/user/repo",
             "description": "<b>A project</b>"},
            {"id": "3", "name": "Local", "link": "https://127.0.0.1/admin"},
            {"id": "4", "name": "Credentials", "link": "https://user@example.com/"},
            {"id": "5", "name": "Insecure", "link": "http://example.org/"},
            {"id": "6", "name": "Injected", "link": "https://example.org/\npath"},
        ])
        rows = backend.normalize_items("community", rows)
        self.assertEqual(["Newer", "Older"], [row["name"] for row in rows])
        self.assertEqual("A project", rows[0]["summary"])
        self.assertIn("searchable", rows[1]["searchText"])
        self.assertEqual(0, rows[1]["timestamp"])
        self.assertEqual("", backend.safe_external_url("https://server.local/"))
        with self.assertRaises(ValueError):
            backend.normalize_community({"error": "bad"})

    def test_meetups_preserve_real_instants_and_sort_future_then_past(self):
        page = b"""<ul>
          <li id="meetup-evt-later"><a href="https://luma.com/later">
            <img src="/images/meetups/evt-later-full.webp" alt="Later">
            <p><time dateTime="2020-01-03T10:00:00+02:00">Fri, Jan 3</time></p>
            <h3>Later</h3><p>Berlin, Germany</p></a></li>
          <li id="meetup-evt-earlier"><a href="https://example.org/earlier">
            <img src="https://evil.example/track.webp" alt="Earlier">
            <p><time dateTime="2020-01-02T00:00:00Z">Jan 2</time></p>
            <h3>Earlier</h3><p>Tokyo</p></a></li>
          <li id="meetup-evt-old"><a href="https://luma.com/old">
            <img src="/images/meetups/evt-old-full.webp" alt="Old">
            <p><time dateTime="2019-12-30T00:00:00Z">Dec 30</time> \xc2\xb7 Paris</p>
            <p>Old</p></a></li>
          <li id="meetup-evt-unsafe"><a href="https://localhost/a">
            <time dateTime="2020-01-02T00:00:00Z">date</time><h3>Unsafe</h3></a></li>
          <li id="meetup-evt-notz"><a href="https://luma.com/a">
            <time dateTime="2020-01-02T00:00:00">date</time><h3>No zone</h3></a></li>
          </ul>"""
        with patch.object(backend.time, "time", return_value=1577836800):
            rows = backend.normalize_events(page)
        self.assertEqual(["Earlier", "Later", "Old"], [row["name"] for row in rows])
        self.assertEqual(1578038400, rows[1]["timestamp"])
        self.assertEqual("Berlin, Germany", rows[1]["summary"])
        self.assertEqual("Paris", rows[2]["summary"])
        self.assertEqual("", rows[0]["thumbnail"])
        self.assertEqual("https://omarchy.org/images/meetups/evt-later-full.webp", rows[1]["thumbnail"])
        with self.assertRaises(ValueError):
            backend.normalize_events(b"<html>No events</html>")

    def test_new_feeds_keep_first_fetch_baseline_and_cached_results_on_failure(self):
        state = backend.empty_state()
        state["baselineEstablished"] = True
        community = {"id": "community:1", "kind": "community", "name": "First",
                     "url": "https://example.org/"}
        event = {"id": "event:evt-first", "kind": "events", "name": "Meetup",
                 "url": "https://luma.com/first", "timestamp": 1900000000}

        def source(key, settings):
            return ({"community": [community], "events": [event]}.get(key, []), "")

        with patch.object(backend, "fetch_source", side_effect=source), patch.object(backend, "save_state"):
            result = backend.perform_fetch(state)
            self.assertFalse(result["items"]["community"][0]["isNew"])
            self.assertFalse(result["items"]["events"][0]["isNew"])

            def unavailable(key, settings):
                if key == "events":
                    raise RuntimeError("Event source unavailable")
                if key == "community":
                    return [community, dict(community, id="community:2", name="Second")], ""
                return [], ""

            with patch.object(backend, "fetch_source", side_effect=unavailable):
                result = backend.perform_fetch(state)
        self.assertTrue(result["items"]["community"][1]["isNew"])
        self.assertEqual("Meetup", result["items"]["events"][0]["name"])
        self.assertEqual("Event source unavailable", result["errors"]["events"])
        self.assertEqual(1900000000, result["items"]["events"][0]["timestamp"])

    def test_system_status_reports_package_check_failure_and_available_update(self):
        ok_version = SimpleNamespace(returncode=0, stdout="4.5.0-3\n", stderr="")
        ok_theme = SimpleNamespace(returncode=0, stdout="Apollo\n", stderr="")
        failure = SimpleNamespace(returncode=1, stdout="", stderr="Cannot fetch updates")
        available = SimpleNamespace(returncode=0,
            stdout="other 1 -> 2\nomarchy 4.5 -> 4.6\n", stderr="")
        for result, status, detail in [(failure, "unknown", "Cannot fetch updates"),
                                       (available, "available", "omarchy 4.5 -> 4.6")]:
            calls = [(ok_version, ""), (ok_theme, ""), (result, "")]
            if status == "available":
                calls.append((available, ""))
            with self.subTest(status=status), \
                    patch.object(backend, "system_command", side_effect=calls):
                response = backend.system_status()
            self.assertEqual("4.5.0-3", response["version"]["value"])
            self.assertEqual("Apollo", response["theme"]["value"])
            self.assertEqual({"status": status, "detail": detail}, response["update"])

    def test_system_status_checks_for_errors_masked_by_checkupdates(self):
        ok = SimpleNamespace(returncode=0, stdout="value", stderr="")
        none = SimpleNamespace(returncode=2, stdout="", stderr="")
        failed_query = SimpleNamespace(returncode=1, stdout="", stderr="Database unavailable")
        with patch.object(backend, "system_command", side_effect=[
                (ok, ""), (ok, ""), (none, ""), (failed_query, "")]):
            response = backend.system_status()
        self.assertEqual({"status": "unknown", "detail": "Database unavailable"}, response["update"])

    def test_system_status_does_not_hide_missing_or_timed_out_commands(self):
        with patch.object(backend, "bounded_run",
                          side_effect=subprocess.TimeoutExpired("checkupdates", 60)):
            result, error = backend.system_command(["checkupdates"], 60)
        self.assertIsNone(result)
        self.assertIn("timed out", error)
        with patch.object(backend, "system_command",
                          side_effect=[(None, "no version"), (None, "no theme"), (None, "no check")]):
            response = backend.system_status()
        self.assertEqual("no version", response["version"]["error"])
        self.assertEqual("no theme", response["theme"]["error"])
        self.assertEqual({"status": "unknown", "detail": "no check"}, response["update"])

    def test_display_preferences_round_trip_without_changing_existing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.object(backend, "state_path", return_value=path):
                self.assertEqual(backend.DEFAULT_DISPLAY, backend.load_display())
                original = backend.empty_state()
                original["readIds"] = ["news:existing"]
                backend.save_state(original)
                saved = {"mode": "window", "width": 950, "height": 700}
                backend.save_display(saved)
                self.assertEqual(saved, backend.load_display())
                self.assertEqual(["news:existing"], backend.load_state()["readIds"])
                self.assertEqual(0o600, path.with_name("display.json").stat().st_mode & 0o777)

    def test_display_preferences_reject_invalid_or_corrupt_data(self):
        for value in [
            {"mode": "closed", "width": 800, "height": 600},
            {"mode": [], "width": 800, "height": 600},
            {"mode": "window", "width": True, "height": 600},
            {"mode": "window", "width": 0, "height": 600},
            {"mode": "window", "width": 999999, "height": 600},
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                backend.validate_display(value)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
                display_path = Path(directory) / "display.json"
                display_path.write_text("{broken", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "invalid"):
                    backend.load_display()
                display_path.write_text("x" * 4097, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "too large"):
                    backend.load_display()

    def test_releases_validate_repository_and_distinguish_prereleases(self):
        release = {"name": "Version 1", "html_url": "https://github.com/omacom/omarchy/releases/tag/v1",
                   "published_at": "2020-01-01T00:00:00Z", "body": "<b>Changes</b>",
                   "author": {"login": "author"}}
        rows = backend.normalize_releases([
            release,
            dict(release, name="", tag_name="v2-rc", prerelease=True,
                 html_url="https://github.com/omacom/omarchy/releases/tag/v2-rc"),
            dict(release, html_url="https://github.com/other/project/releases/tag/v1"),
            dict(release, html_url="https://example.com/omacom/omarchy/releases/tag/v1"),
            dict(release, draft=True),
        ])
        self.assertEqual(["Version 1", "v2-rc"], [row["name"] for row in rows])
        self.assertEqual("Changes", rows[0]["summary"])
        self.assertEqual(1577836800, rows[0]["timestamp"])
        self.assertEqual("Omarchy pre-release", rows[1]["source"])
        with self.assertRaises(ValueError):
            backend.normalize_releases({"message": "rate limited"})

    def test_manual_index_keeps_full_search_text_and_safe_section_links(self):
        rows = backend.normalize_manual([
            {"kind": "manual", "slug": "index", "title": "Welcome", "heading": None,
             "hash": None, "text": "a" * 700 + " searchable ending"},
            {"kind": "manual", "slug": "hotkeys", "title": "Hotkeys",
             "heading": "Basics", "hash": "the-basics", "text": "Description"},
            {"kind": "manual", "slug": "../escape", "title": "Unsafe", "text": "Bad"},
            {"kind": "manual", "slug": "hotkeys", "title": "Unsafe",
             "hash": "x?redirect=evil", "text": "Bad"},
            {"kind": "news", "slug": "other", "title": "Not manual"},
        ])
        normalized = backend.normalize_items("manual", rows)
        self.assertEqual(["Welcome", "Hotkeys: Basics"], [row["name"] for row in normalized])
        self.assertTrue(normalized[0]["searchText"].endswith("searchable ending"))
        self.assertNotIn("searchable ending", normalized[0]["summary"])
        self.assertEqual("https://omarchy.org/manual/hotkeys/#the-basics", normalized[1]["url"])
        self.assertEqual("", backend.safe_manual_url("https://omarchy.org/manual/hotkeys/#bad%0a"))
        self.assertEqual("", backend.safe_manual_url("https://evil.example/manual/hotkeys/#basics"))
        with self.assertRaises(ValueError):
            backend.normalize_manual([])

    def test_hotkeys_preserve_categories_multiple_description_columns_and_order(self):
        page = b"""<table><tr><td>Ignored</td><td>Outside article</td></tr></table>
          <article><h2 id="system">System <a href="#system">#</a></h2>
          <table><tr><th>Shortcut</th><th>Action</th></tr>
          <tr><td><kbd>Super</kbd> + Q</td><td>Quit</td><td>Current window</td></tr>
          <tr><td>tdl [&lt;ai&gt;]</td><td>Terminal</td></tr></table>
          <h2 id="bad?fragment">Bad</h2><table><tr><td>Bad</td><td>Bad</td></tr></table>
          </article>"""
        rows = backend.normalize_items("hotkeys", backend.normalize_hotkeys(page))
        self.assertEqual(["Super + Q", "tdl [<ai>]"], [row["name"] for row in rows])
        self.assertEqual("Quit · Current window", rows[0]["summary"])
        self.assertEqual("System", rows[0]["source"])
        self.assertEqual("https://omarchy.org/manual/hotkeys/#system", rows[0]["url"])
        with self.assertRaises(ValueError):
            backend.normalize_hotkeys(b"<article>No table</article>")

    def test_new_sources_baseline_then_report_later_releases_and_preserve_existing_state(self):
        state = backend.empty_state()
        old = {"id": "news:existing", "kind": "news", "name": "Existing",
               "url": "https://omarchy.org/news/existing/"}
        state.update(baselineEstablished=True, knownIds=[old["id"]],
                     readIds=[old["id"]], savedItems=[dict(old)])
        state["sources"]["news"] = {"items": [dict(old)], "fetchedAt": 1}
        release = {"id": "release:first", "kind": "releases", "name": "First",
                   "url": "https://github.com/omacom/omarchy/releases/tag/v1"}
        def source(key, settings):
            return ({"news": [old], "releases": [release]}.get(key, []), "")
        with patch.object(backend, "fetch_source", side_effect=source), \
                patch.object(backend, "save_state"):
            result = backend.perform_fetch(state)
            self.assertFalse(result["items"]["releases"][0]["isNew"])
            self.assertTrue(result["items"]["news"][0]["isRead"])
            self.assertTrue(result["items"]["news"][0]["isSaved"])
            next_release = dict(release, id="release:second", name="Second",
                                url="https://github.com/omacom/omarchy/releases/tag/v2")
            def updated_source(key, settings):
                return ([release, next_release] if key == "releases" else
                        {"news": [old]}.get(key, [])), ""
            with patch.object(backend, "fetch_source", side_effect=updated_source):
                updated = backend.perform_fetch(state)
        self.assertEqual(["release:second"],
                         [item["id"] for item in updated["items"]["releases"] if item["isNew"]])

    def test_reference_state_round_trips_search_text_and_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
                item = backend.normalize_manual([{"kind": "manual", "slug": "hotkeys",
                    "title": "Hotkeys", "heading": "Basics", "hash": "basics",
                    "text": "Full chapter text"}])[0]
                state = backend.empty_state()
                state["sources"]["manual"] = {"items": [item], "fetchedAt": 1}
                state["savedItems"] = [item]
                backend.save_state(state)
                restored = backend.load_state()
        self.assertEqual("Full chapter text", restored["sources"]["manual"]["items"][0]["searchText"])
        self.assertEqual("https://omarchy.org/manual/hotkeys/#basics", restored["savedItems"][0]["url"])

    def test_plugin_rows_validate_ids_and_emit_marketplace_links(self):
        rows = backend.normalize_plugins({
            "plugins": [
                {"id": "author.plugin", "name": "<b>Useful</b>", "description": "A plugin",
                 "previewThumbnail": "assets/img/plugins/example-card.webp"},
                {"id": "../escape", "name": "Bad"},
                {"id": "empty", "name": ""},
            ]
        })
        self.assertEqual(1, len(rows))
        self.assertEqual("Useful", rows[0]["name"])
        self.assertEqual("https://plugins.omarchy.org/assets/img/plugins/example-card.webp",
                         rows[0]["thumbnail"])
        self.assertEqual(
            "https://plugins.omarchy.org/plugin.html?id=author.plugin",
            rows[0]["url"],
        )

    def test_official_themes_preserve_order_and_validate_cards(self):
        page = b"""<html><body>
          <a href="https://github.com/Artist/first"><img src="/assets/themes/first.webp">
            <span>First &amp; Best</span></a>
          <a href="https://github.com/artist/second"><img src="/assets/themes/second.webp">
            <span>Second</span></a>
          <a href="https://example.com/attacker"><img src="/assets/themes/bad.webp">Bad</a>
          <a href="https://github.com/artist/third"><img src="https://example.com/track.webp">Bad</a>
        </body></html>"""
        rows = backend.normalize_themes(page)
        self.assertEqual(["First & Best", "Second"], [row["name"] for row in rows])
        self.assertEqual("https://github.com/Artist/first", rows[0]["url"])
        self.assertEqual("https://omarchy.org/assets/themes/first.webp", rows[0]["thumbnail"])
        self.assertEqual(0, rows[0]["timestamp"])
        self.assertEqual(["First & Best", "Second"],
                         [row["name"] for row in backend.normalize_items("themes", rows)])
        with self.assertRaisesRegex(ValueError, "no recognized theme cards"):
            backend.normalize_themes(b"<html>not a themes page</html>")

    def test_catalogs_sort_before_applying_the_source_limit(self):
        plugins = [{"id": f"plugin-{i}", "name": f"Plugin {i}", "addedAt": "2020-01-01"}
                   for i in range(160)]
        plugins[-1]["addedAt"] = "2020-02-01"
        with patch.object(backend, "MAX_ITEMS_PER_SOURCE", 150):
            rows = backend.normalize_plugins({"plugins": plugins})
        self.assertEqual(150, len(rows))
        self.assertEqual("plugin:plugin-159", rows[0]["id"])

    def test_untrusted_thumbnail_urls_are_rejected(self):
        for kind, value in [
            ("plugins", "//example.com/assets/img/plugins/a.webp"),
            ("plugins", "assets/img/plugins/../other.webp"),
            ("plugins", "assets/img/plugins/image.svg"),
            ("themes", "https://example.com/v1/previews/x/" + "a" * 40 + "/480.webp"),
            ("themes", "https://omarchy.org/assets/themes/../track.webp"),
            ("themes", "https://omarchy.org/assets/themes/track.svg"),
            ("videos", "https://i.ytimg.com/redirect?url=https://example.com/"),
            ("news", "http://omarchy.org/news/image.png"),
        ]:
            with self.subTest(kind=kind, value=value):
                self.assertEqual("", backend.safe_thumbnail(kind, value))
        item = backend.valid_item({"id": "video:abcdefghijk", "kind": "videos", "name": "Safe",
                                   "url": "https://www.youtube.com/watch?v=abcdefghijk",
                                   "thumbnail": "https://example.com/tracking.png"})
        self.assertEqual("", item["thumbnail"])

    def test_source_messages_survive_local_state_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
                state = backend.empty_state()
                state["sources"]["themes"] = {"items": [], "fetchedAt": 0, "message": "Registry fallback"}
                backend.save_state(state)
                self.assertEqual("Registry fallback", backend.public_state(backend.load_state())["errors"]["themes"])

    def test_youtube_search_requests_approximate_dates_and_newest_order(self):
        payload = {"entries": [{"id": "abcdefghijk", "title": "Video", "timestamp": 1700000000}]}
        result = type("Result", (), {"stdout": json.dumps(payload).encode(),
                                    "stderr": b"", "returncode": 0})()
        with patch.object(backend.shutil, "which", return_value="/usr/bin/yt-dlp"), \
                patch.object(backend, "bounded_run", return_value=result) as run:
            rows = backend.youtube_search(50, "all")
        command = run.call_args.args[0]
        self.assertIn("youtubetab:approximate_date=1", command)
        self.assertIn("sp=CAI%3D", command[-1])
        self.assertEqual(1700000000, rows[0]["timestamp"])
        self.assertEqual("https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg", rows[0]["thumbnail"])

    def test_news_feed_accepts_rss_and_rejects_non_omarchy_links(self):
        xml = b"""<rss><channel><item>
          <title><![CDATA[<b>Omarchy news</b>]]></title>
          <link>https://omarchy.org/news/example</link>
          <description>A story</description><guid>story-1</guid>
          <pubDate>Fri, 06 Nov 2026 12:00:00 GMT</pubDate>
        </item><item><title>Other</title><link>https://example.com/</link></item>
        </channel></rss>"""
        rows = backend.normalize_news(xml)
        self.assertEqual(2, len(rows))
        self.assertEqual("Omarchy news", rows[0]["name"])
        self.assertEqual("https://omarchy.org/news/example", rows[0]["url"])
        self.assertEqual(backend.NEWS_HOME, rows[1]["url"])

    def test_news_uses_first_safe_embedded_or_enclosed_image(self):
        xml = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
          <item><title>Embedded</title><link>https://omarchy.org/news/story/</link>
            <description><![CDATA[<img src="https://example.com/track.png">
              <img src="cover.webp">]]></description></item>
          <item><title>Enclosed</title><link>https://omarchy.org/news/other/</link>
            <media:thumbnail url="https://omarchy.org/news/other/cover.png"/></item>
        </channel></rss>"""
        rows = backend.normalize_news(xml)
        self.assertEqual("https://omarchy.org/news/story/cover.webp", rows[0]["thumbnail"])
        self.assertEqual("https://omarchy.org/news/other/cover.png", rows[1]["thumbnail"])

    def test_invalid_cached_items_are_discarded(self):
        rows = backend.normalize_items("videos", [
            {"id": "video:abcdefghijk", "kind": "videos", "name": "<img src=x>",
             "url": "javascript:alert(1)"},
            {"id": "video:abcdefghijk", "kind": "videos", "name": "Safe",
             "url": "https://www.youtube.com/watch?v=abcdefghijk"},
        ])
        self.assertEqual(1, len(rows))
        self.assertEqual("Safe", rows[0]["name"])

    def test_settings_are_validated_and_keep_native_types(self):
        settings = backend.valid_settings({
            "refreshOnOpen": "false",
            "videosLimit": "150",
            "youtubeRange": "invalid",
            "showPreviews": "false", "refresh_news": False,
            "catchUpLimit": "12", "density": "compact",
            "dashboardOrder": "saved,events,catchup,system",
            "savedLimit": "999",
        })
        self.assertIs(settings["refreshOnOpen"], False)
        self.assertEqual(150, settings["videosLimit"])
        self.assertNotIn("youtubeRange", settings)
        self.assertIs(settings["showPreviews"], False)
        self.assertIs(settings["refresh_news"], False)
        self.assertEqual(12, settings["catchUpLimit"])
        self.assertEqual("compact", settings["density"])
        self.assertEqual("saved,events,catchup,system", settings["dashboardOrder"])
        self.assertNotIn("savedLimit", settings)
        periodic = backend.valid_settings({"refreshInterval": "60", "periodicRefresh": "false"})
        self.assertEqual(60, periodic["refreshInterval"])
        self.assertIs(periodic["periodicRefresh"], False)
        sections = backend.valid_settings({"section_plugins": "false", "section_system": "false"})
        self.assertIs(sections["section_plugins"], False)
        self.assertIs(sections["section_system"], False)
        self.assertIs(backend.empty_state()["settings"]["section_plugins"], True)
        self.assertIs(backend.empty_state()["settings"]["newItemNotifications"], True)
        self.assertIs(backend.valid_settings({"newItemNotifications": "false"})["newItemNotifications"], False)
        self.assertNotIn("refreshInterval", backend.valid_settings({"refreshInterval": "9"}))

    def test_navigation_width_is_bounded_persisted_and_reset_with_appearance(self):
        for width in (160, 190, 220):
            self.assertEqual(width, backend.valid_settings({"navigationWidth": str(width)})["navigationWidth"])
        for width in (159, 221, "190.5", True):
            self.assertNotIn("navigationWidth", backend.valid_settings({"navigationWidth": width}))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            backend.save_state(backend.empty_state())
            with patch.object(sys, "argv", ["Backend.py", "set-setting", "navigationWidth", "220"]), \
                    patch("builtins.print"):
                backend.main()
            self.assertEqual(220, backend.load_state()["settings"]["navigationWidth"])
            original = backend.state_path().read_bytes()
            with patch.object(sys, "argv", ["Backend.py", "set-setting", "navigationWidth", "221"]):
                with self.assertRaises(ValueError):
                    backend.main()
            self.assertEqual(original, backend.state_path().read_bytes())
            with patch.object(sys, "argv", ["Backend.py", "reset-settings", "general"]), \
                    patch("builtins.print"):
                backend.main()
            self.assertEqual(160, backend.load_state()["settings"]["navigationWidth"])
            hidden = backend.load_state()
            hidden["settings"]["section_plugins"] = False
            backend.save_state(hidden)
            with patch.object(sys, "argv", ["Backend.py", "reset-settings", "sections"]), \
                    patch("builtins.print"):
                backend.main()
            self.assertIs(backend.load_state()["settings"]["section_plugins"], True)

    def test_filters_round_trip_opt_out_and_group_resets_preserve_history(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            state = backend.empty_state()
            state["readIds"] = ["news:old"]
            state["savedItems"] = [{"id": "news:old", "kind": "news", "name": "Saved",
                                    "url": "https://omarchy.org/news/old/"}]
            state["settings"]["density"] = "compact"
            filters = {"plugins": {"query": "<b>literal</b>  ", "terms": ["dark", "Alice"], "range": "week"},
                       "saved": {"query": "keep", "terms": [], "range": "all"}}
            with patch.object(sys, "argv", ["Backend.py", "save-filters", json.dumps(filters)]), \
                    patch("builtins.print"):
                backend.mutate(state, "save-filters")
            restored = backend.load_state()
            self.assertEqual(filters, restored["filters"])
            self.assertEqual(filters, backend.public_state(restored)["filters"])
            with patch.object(sys, "argv", ["Backend.py", "set-setting", "remember_plugins", "false"]), \
                    patch("builtins.print"):
                backend.mutate(restored, "set-setting")
            self.assertNotIn("plugins", backend.load_state()["filters"])
            with patch.object(sys, "argv", ["Backend.py", "reset-settings", "saved"]), \
                    patch("builtins.print"):
                backend.mutate(restored, "reset-settings")
            final = backend.load_state()
            self.assertEqual({}, final["filters"])
            self.assertEqual(["news:old"], final["readIds"])
            self.assertEqual("Saved", final["savedItems"][0]["name"])
            self.assertEqual("compact", final["settings"]["density"])
            self.assertIs(final["settings"]["remember_plugins"], False)
            with patch.object(sys, "argv", ["Backend.py", "reset-settings", "general"]), \
                    patch("builtins.print"):
                backend.mutate(final, "reset-settings")
            self.assertEqual("comfortable", backend.load_state()["settings"]["density"])
            self.assertEqual(["news:old"], backend.load_state()["readIds"])
            reset = backend.load_state()
            reset["settings"]["newItemNotifications"] = False
            backend.save_state(reset)
            with patch.object(sys, "argv", ["Backend.py", "reset-settings", "refresh"]), \
                    patch("builtins.print"):
                backend.mutate(reset, "reset-settings")
            self.assertIs(backend.load_state()["settings"]["newItemNotifications"], True)

    def test_bulk_read_actions_cover_whole_section_and_saved_items(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            state = backend.empty_state()
            first = {"id": "news:first", "kind": "news", "name": "First",
                     "url": "https://omarchy.org/news/first/"}
            hidden = {"id": "news:hidden", "kind": "news", "name": "Hidden",
                      "url": "https://omarchy.org/news/hidden/"}
            other = {"id": "plugins:other", "kind": "plugins", "name": "Other",
                     "url": "https://github.com/example/plugin"}
            state["sources"]["news"] = {"items": [first, hidden], "fetchedAt": 1}
            state["sources"]["plugins"] = {"items": [other], "fetchedAt": 1}
            state["savedItems"] = [hidden, other]
            state["filters"] = {"news": {"query": "First", "terms": [], "range": "all"}}
            state["readIds"] = [other["id"]]
            state["newIds"] = [first["id"], hidden["id"]]
            with patch.object(sys, "argv", ["Backend.py", "mark-all-read", "news"]), \
                    patch("builtins.print"):
                backend.mutate(state, "mark-all-read")
            restored = backend.load_state()
            self.assertEqual({first["id"], hidden["id"], other["id"]}, set(restored["readIds"]))
            self.assertEqual([], restored["newIds"])
            self.assertTrue(backend.public_state(restored)["items"]["saved"][0]["isRead"])
            with patch.object(sys, "argv", ["Backend.py", "mark-all-unread", "news"]), \
                    patch("builtins.print"):
                backend.mutate(restored, "mark-all-unread")
            self.assertEqual([other["id"]], backend.load_state()["readIds"])
            with patch.object(sys, "argv", ["Backend.py", "mark-all-unread", "saved"]), \
                    patch("builtins.print"):
                backend.main()
            self.assertEqual([], backend.load_state()["readIds"])
            self.assertEqual([], backend.load_state()["newIds"])
            self.assertEqual(state["filters"], backend.load_state()["filters"])
            with patch.object(sys, "argv", ["Backend.py", "mark-all-read", "dashboard"]), \
                    patch("builtins.print"):
                backend.main()
            self.assertEqual({first["id"], hidden["id"], other["id"]},
                             set(backend.load_state()["readIds"]))
            with patch.object(sys, "argv", ["Backend.py", "mark-all-unread", "dashboard"]), \
                    patch("builtins.print"):
                backend.main()
            self.assertEqual([], backend.load_state()["readIds"])

    def test_dashboard_bulk_actions_skip_hidden_feeds_but_include_their_saved_items(self):
        for command in ("mark-all-read", "mark-all-unread"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory, \
                    patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
                state = backend.empty_state()
                visible = {"id": "news:visible", "kind": "news", "name": "Visible",
                           "url": "https://omarchy.org/news/visible/"}
                hidden = {"id": "plugin:hidden", "kind": "plugins", "name": "Hidden",
                          "url": "https://github.com/example/hidden"}
                saved = {"id": "plugin:saved", "kind": "plugins", "name": "Saved",
                         "url": "https://github.com/example/saved"}
                state["settings"]["section_plugins"] = False
                state["sources"]["news"] = {"items": [visible], "fetchedAt": 1}
                state["sources"]["plugins"] = {"items": [hidden, saved], "fetchedAt": 1}
                state["savedItems"] = [saved]
                all_ids = {visible["id"], hidden["id"], saved["id"]}
                state["readIds"] = sorted(all_ids) if command == "mark-all-unread" else []
                state["newIds"] = [] if command == "mark-all-unread" else sorted(all_ids)
                backend.save_state(state)
                original = backend.load_state()

                with patch.object(sys, "argv", ["Backend.py", command, "dashboard"]), \
                        patch("builtins.print"):
                    backend.main()

                restored = backend.load_state()
                expected_read = {hidden["id"]} if command == "mark-all-unread" \
                    else {visible["id"], saved["id"]}
                self.assertEqual(expected_read, set(restored["readIds"]))
                self.assertEqual([] if command == "mark-all-unread" else [hidden["id"]],
                                 restored["newIds"])
                self.assertEqual(original["sources"], restored["sources"])
                self.assertIs(restored["settings"]["section_plugins"], False)

    def test_scroll_read_batch_is_persisted_and_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            state = backend.empty_state()
            state["savedItems"] = [{"id": "news:saved", "kind": "news", "name": "Saved",
                                    "url": "https://omarchy.org/news/saved/"}]
            state["sources"]["manual"] = {"items": [
                {"id": "manual:first", "kind": "manual", "name": "Manual",
                 "url": "https://omarchy.org/manual/hotkeys/"}], "fetchedAt": 1}
            state["newIds"] = ["news:saved"]
            backend.save_state(state)
            for command, argument in (
                    ("mark-all-read", "system"), ("mark-all-unread", "unknown"),
                    ("mark-read-items", "{}"), ("mark-read-items", "[]"),
                    ("mark-read-items", '["news:missing"]'), ("mark-read-items", "[7]"),
                    ("mark-read-items", json.dumps(["news:saved"] * 201))):
                original = backend.state_path().read_bytes()
                with patch.object(sys, "argv", ["Backend.py", command, argument]):
                    with self.assertRaises(ValueError):
                        backend.main()
                self.assertEqual(original, backend.state_path().read_bytes())
            with patch.object(sys, "argv", ["Backend.py", "mark-read-items",
                                           '["news:saved","manual:first"]']), patch("builtins.print"):
                backend.main()
            restored = backend.load_state()
            self.assertEqual({"news:saved", "manual:first"}, set(restored["readIds"]))
            self.assertEqual([], restored["newIds"])

    def test_invalid_filter_updates_do_not_overwrite_persisted_state(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            state = backend.empty_state()
            backend.save_state(state)
            original = backend.state_path().read_bytes()
            for filters in ({"unknown": {}}, {"news": {"terms": ["x"] * 17}},
                            {"news": {"query": "x" * 241}}, {"news": {"range": "invalid"}}):
                with patch.object(sys, "argv", ["Backend.py", "save-filters", json.dumps(filters)]):
                    with self.assertRaises(ValueError):
                        backend.mutate(state, "save-filters")
                self.assertEqual(original, backend.state_path().read_bytes())

    def test_clear_saved_removes_all_bookmarks_but_preserves_other_state(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            state = backend.empty_state()
            item = {"id": "news:old", "kind": "news", "name": "Read story",
                    "url": "https://omarchy.org/news/old/"}
            state["savedItems"] = [item, dict(item, id="news:other", name="Unread story")]
            state["readIds"] = [item["id"]]
            state["knownIds"] = [item["id"]]
            state["newIds"] = [item["id"]]
            state["sources"]["news"] = {"items": [item], "fetchedAt": 10, "message": ""}
            state["settings"]["density"] = "compact"
            state["filters"] = {"saved": {"query": "hidden", "terms": [], "range": "all"}}
            backend.save_state(state)
            original = backend.load_state()
            with patch.object(sys, "argv", ["Backend.py", "clear-saved"]), patch("builtins.print") as output:
                backend.main()
            payload = json.loads(output.call_args.args[0])
            self.assertEqual([], payload["items"]["saved"])
            self.assertFalse(payload["items"]["news"][0]["isSaved"])
            self.assertTrue(payload["items"]["news"][0]["isRead"])
            restored = backend.load_state()
            self.assertEqual([], restored.pop("savedItems"))
            original.pop("savedItems")
            self.assertEqual(original, restored)
            with patch.object(sys, "argv", ["Backend.py", "clear-saved", "unexpected"]):
                with self.assertRaises(ValueError):
                    backend.main()

    def test_on_open_refresh_honors_source_switches_manual_refresh_does_not(self):
        state = backend.empty_state()
        state["settings"]["refresh_news"] = False
        with patch.object(backend, "load_state", return_value=state), \
                patch.object(backend, "perform_fetch", return_value={}) as fetch, patch("builtins.print"):
            with patch.object(sys, "argv", ["Backend.py", "fetch", "on-open"]):
                backend.main()
            self.assertNotIn("news", fetch.call_args.args[1])
            self.assertIn("plugins", fetch.call_args.args[1])
            with patch.object(sys, "argv", ["Backend.py", "fetch"]):
                backend.main()
            self.assertEqual(list(backend.SOURCE_KEYS), fetch.call_args.args[1])
            state["settings"]["refreshOnOpen"] = False
            with patch.object(sys, "argv", ["Backend.py", "fetch", "on-open"]):
                backend.main()
            self.assertEqual([], fetch.call_args.args[1])
            state["settings"]["refreshOnOpen"] = True
            state["settings"]["periodicVideos"] = False
            with patch.object(sys, "argv", ["Backend.py", "fetch", "scheduled"]):
                backend.main()
            self.assertNotIn("videos", fetch.call_args.args[1])
            self.assertIn("plugins", fetch.call_args.args[1])
            state["settings"]["periodicVideos"] = True
            with patch.object(sys, "argv", ["Backend.py", "fetch", "scheduled"]):
                backend.main()
            self.assertIn("videos", fetch.call_args.args[1])
            state["settings"]["periodicRefresh"] = False
            with patch.object(sys, "argv", ["Backend.py", "fetch", "scheduled"]):
                backend.main()
            self.assertEqual([], fetch.call_args.args[1])

    def test_hidden_sections_are_excluded_from_all_refresh_modes_and_direct_fetches(self):
        state = backend.empty_state()
        state["settings"]["section_news"] = False
        state["sources"]["news"] = {
            "items": [{"id": "news:cached", "kind": "news", "name": "Cached",
                       "url": "https://omarchy.org/news/cached/"}],
            "fetchedAt": 123,
            "message": "",
        }
        for args in (["fetch"], ["fetch", "on-open"], ["fetch", "scheduled"]):
            with self.subTest(args=args), \
                    patch.object(backend, "load_state", return_value=state), \
                    patch.object(backend, "perform_fetch", return_value={}) as fetch, \
                    patch("builtins.print"):
                with patch.object(sys, "argv", ["Backend.py"] + args):
                    backend.main()
                self.assertNotIn("news", fetch.call_args.args[1])
                self.assertIn("plugins", fetch.call_args.args[1])

        with patch.object(backend, "fetch_source") as fetch, patch.object(backend, "save_state"):
            result = backend.perform_fetch(state, ["news"])
        fetch.assert_not_called()
        self.assertEqual("Cached", result["items"]["news"][0]["name"])
        self.assertEqual(123, result["lastFetched"]["news"])

    def test_selective_refresh_keeps_unselected_cache_and_new_flags(self):
        state = backend.empty_state()
        state["baselineEstablished"] = True
        cached = {"id": "news:old", "kind": "news", "name": "Cached",
                  "url": "https://omarchy.org/news/old/"}
        state["sources"]["news"] = {"items": [cached], "fetchedAt": 10, "message": "Earlier warning"}
        state["newIds"] = [cached["id"]]
        state["knownIds"] = [cached["id"]]
        plugin = {"id": "plugin:one", "kind": "plugins", "name": "First plugin",
                  "url": "https://plugins.omarchy.org/"}
        with patch.object(backend, "fetch_source", return_value=([plugin], "")) as fetch, \
                patch.object(backend, "save_state"):
            payload = backend.perform_fetch(state, ["plugins"])
            fetch.assert_called_once_with("plugins", state["settings"])
            self.assertEqual(10, payload["lastFetched"]["news"])
            self.assertEqual("Earlier warning", payload["errors"]["news"])
            self.assertTrue(payload["items"]["news"][0]["isNew"])
            self.assertFalse(payload["items"]["plugins"][0]["isNew"])
            fetch.reset_mock()
            backend.perform_fetch(state, [])
            fetch.assert_not_called()

    def test_new_items_stay_new_until_read_and_badges_use_unread_new_counts(self):
        state = backend.empty_state()
        state["baselineEstablished"] = True
        state["knownIds"] = ["news:old"]
        state["sources"]["news"] = {
            "items": [{"id": "news:old", "kind": "news", "name": "Old",
                       "url": "https://omarchy.org/news/old/"}],
            "fetchedAt": 1,
        }
        row = {"id": "news:new", "kind": "news", "name": "New item",
               "url": "https://omarchy.org/news/new/"}
        with patch.object(backend, "fetch_source", side_effect=lambda key, settings:
                          ([row] if key == "news" else [], "")), patch.object(backend, "save_state"):
            first = backend.perform_fetch(state)
            self.assertEqual(1, first["newCounts"]["news"])
            second = backend.perform_fetch(state)
            self.assertTrue(second["items"]["news"][0]["isNew"])
            self.assertEqual(1, second["newCounts"]["news"])
            with patch.object(sys, "argv", ["Backend.py", "mark-read", "news:new"]), patch("builtins.print"):
                backend.mutate(state, "mark-read")
            acknowledged = backend.public_state(state)
        self.assertFalse(acknowledged["items"]["news"][0]["isNew"])
        self.assertEqual(0, acknowledged["newCounts"]["news"])

    def test_local_state_round_trips_saved_and_read_items(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.object(backend, "state_path", return_value=path):
                state = backend.empty_state()
                state["baselineEstablished"] = True
                state["newIds"] = ["video:abcdefghijk"]
                state["knownIds"] = ["video:abcdefghijk"]
                state["readIds"] = ["video:abcdefghijk"]
                state["savedItems"] = [{
                    "id": "video:abcdefghijk", "kind": "videos",
                    "name": "A video", "url": "https://www.youtube.com/watch?v=abcdefghijk",
                    "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg",
                }]
                backend.save_state(state)
                restored = backend.load_state()
        self.assertEqual(["video:abcdefghijk"], restored["newIds"])
        self.assertEqual(["video:abcdefghijk"], restored["readIds"])
        self.assertEqual("A video", restored["savedItems"][0]["name"])
        self.assertEqual("https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg",
                         restored["savedItems"][0]["thumbnail"])

    def test_refresh_updates_existing_saved_preview(self):
        state = backend.empty_state()
        item = {"id": "video:abcdefghijk", "kind": "videos", "name": "A video",
                "url": "https://www.youtube.com/watch?v=abcdefghijk"}
        state["savedItems"] = [dict(item)]
        image = "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"
        def source(key, settings):
            return ([dict(item, thumbnail=image)] if key == "videos" else []), ""
        with patch.object(backend, "fetch_source", side_effect=source), \
                patch.object(backend, "save_state"):
            backend.perform_fetch(state)
        self.assertEqual(image, state["savedItems"][0]["thumbnail"])

    def test_theme_source_migration_preserves_saved_and_read_without_false_new_items(self):
        state = backend.empty_state()
        old = {"id": "theme:legacy", "kind": "themes", "name": "Old",
               "url": "https://github.com/Artist/Theme", "timestamp": 1700000000}
        state["baselineEstablished"] = True
        state["knownIds"] = ["theme:legacy"]
        state["readIds"] = ["theme:legacy"]
        state["savedItems"] = [dict(old)]
        state["sources"]["themes"] = {"items": [dict(old)], "fetchedAt": 1}
        page = b"""<a href="https://github.com/artist/theme/">
            <img src="/assets/themes/theme.webp"><span>Theme</span></a>
            <a href="https://github.com/artist/other"><img src="/assets/themes/other.webp">
            <span>Other</span></a>"""
        rows = backend.normalize_themes(page)
        def source(key, settings):
            return (rows if key == "themes" else []), ""
        with patch.object(backend, "fetch_source", side_effect=source), \
                patch.object(backend, "save_state"):
            result = backend.perform_fetch(state)
        self.assertEqual("theme:legacy", result["items"]["themes"][0]["id"])
        self.assertTrue(result["items"]["themes"][0]["isRead"])
        self.assertTrue(result["items"]["themes"][0]["isSaved"])
        self.assertFalse(any(item["isNew"] for item in result["items"]["themes"]))
        self.assertEqual("omarchy-site", state["sources"]["themes"]["provider"])
        self.assertEqual("https://omarchy.org/assets/themes/theme.webp",
                         result["items"]["saved"][0]["thumbnail"])


class ProcessBoundaryTests(unittest.TestCase):
    def test_helper_term_cleans_main_thread_threadpool_and_spawn_window_children(self):
        original_child = """
import os, pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
while True: time.sleep(1)
"""
        for mode in ("main", "threadpool", "spawn-window"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                child_script = base / "child.py"
                child_script.write_text(original_child)
                helper_script = base / "helper.py"
                helper_script.write_text("""
import importlib.util, json, pathlib, signal, subprocess, sys, time
spec = importlib.util.spec_from_file_location("backend", sys.argv[1])
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
signal.signal(signal.SIGTERM, b.interrupt_request)
base = pathlib.Path(sys.argv[2])
mode = sys.argv[3]
command = [sys.executable, str(base / "child.py")]
if mode == "spawn-window":
    original = subprocess.Popen
    def delayed_popen(*args, **kwargs):
        process = original(*args, **kwargs)
        time.sleep(0.4)
        return process
    b.subprocess.Popen = delayed_popen
try:
    if mode == "threadpool":
        def fetch(key, settings):
            b.bounded_run(command + [str(base / (key + ".pid"))], 10, 1024)
            return [], ""
        b.fetch_source = fetch
        b.perform_fetch(b.empty_state(), ["plugins", "themes"])
    else:
        b.bounded_run(command + [str(base / "main.pid")], 10, 1024)
except RuntimeError as error:
    print(json.dumps({"error": str(error)}), file=sys.stderr)
    sys.exit(1)
""")
                process = subprocess.Popen([sys.executable, str(helper_script), str(BACKEND_PATH),
                                            str(base), mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    expected = 2 if mode == "threadpool" else 1
                    deadline = time.monotonic() + 3
                    while len(list(base.glob("*.pid"))) < expected and time.monotonic() < deadline:
                        time.sleep(0.01)
                    pids = [int(path.read_text()) for path in base.glob("*.pid")]
                    self.assertEqual(expected, len(pids))
                    process.send_signal(signal.SIGTERM)
                    output, diagnostic = process.communicate(timeout=3)
                    self.assertEqual(1, process.returncode, diagnostic)
                    self.assertEqual(b"", output)
                    self.assertIn("interrupted", json.loads(diagnostic)["error"])
                    for pid in pids:
                        status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                                capture_output=True, text=True, check=False).stdout.strip()
                        self.assertTrue(not status or status.startswith("Z"), status)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()

    def test_completed_process_keeps_binary_text_newlines_and_exit_status(self):
        command = [sys.executable, "-c",
                   "import os; os.write(1,b'one\\r\\ntwo\\r\\xff'); os.write(2,b'error'); exit(7)"]
        result = backend.bounded_run(command, 3, 1024)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual(command, result.args)
        self.assertEqual(7, result.returncode)
        self.assertEqual(b"one\r\ntwo\r\xff", result.stdout)
        self.assertEqual(b"error", result.stderr)
        result, error = backend.system_command(command, 3)
        self.assertEqual("", error)
        self.assertEqual("one\ntwo\n\ufffd", result.stdout)
        self.assertEqual("error", result.stderr)
        self.assertEqual(7, result.returncode)

    def test_stdout_and_stderr_share_streaming_limit_and_reap_process(self):
        original_popen = subprocess.Popen
        for stream in (1, 2):
            started_processes = []

            def start_process(*args, **kwargs):
                process = original_popen(*args, **kwargs)
                started_processes.append(process)
                return process

            command = [sys.executable, "-c",
                       f"import os; os.write({3 - stream}, b'small'); "
                       f"exec('while True: os.write({stream}, b\"x\" * 4096)')"]
            with self.subTest(stream=stream), \
                    patch.object(backend.subprocess, "Popen", side_effect=start_process), \
                    patch.object(backend, "MAX_OUTPUT_BYTES", 1024):
                started = time.monotonic()
                result, error = backend.system_command(command, 3)
                self.assertIsNone(result)
                self.assertIn("size limit", error)
                self.assertLess(time.monotonic() - started, 2)
                self.assertEqual(1, len(started_processes))
                self.assertIsNotNone(started_processes[0].returncode)
                with self.assertRaises(ChildProcessError):
                    os.waitpid(started_processes[0].pid, os.WNOHANG)

    def test_whole_deadline_kills_descendants_even_after_parent_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "child.pid"
            command = [sys.executable, "-c", """
import os, pathlib, signal, sys, time
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
    while True:
        os.write(1, b"slow")
        time.sleep(0.05)
os._exit(0)
""", str(pid_path)]
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                backend.bounded_run(command, 0.35, 1024)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertIsInstance(raised.exception.stdout, bytes)
            child = int(pid_path.read_text())
            status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                                    capture_output=True, text=True, check=False).stdout.strip()
            self.assertTrue(not status or status.startswith("Z"), status)

    def test_youtube_stderr_limit_and_invalid_data_surface_existing_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "yt-dlp"
            command.write_text("#!/usr/bin/python3\nimport os\nwhile True: os.write(2, b'x' * 4096)\n")
            command.chmod(0o700)
            with patch.object(backend.shutil, "which", return_value=str(command)), \
                    patch.object(backend, "MAX_RESPONSE_BYTES", 1024):
                with self.assertRaisesRegex(ValueError, "search response exceeded"):
                    backend.youtube_search(50, "all")
        result = subprocess.CompletedProcess([], 1, b"", b"real failure")
        with patch.object(backend.shutil, "which", return_value="yt-dlp"), \
                patch.object(backend, "bounded_run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "real failure"):
                backend.youtube_search(50, "all")


class StateBoundaryTests(unittest.TestCase):
    def test_writable_ancestors_are_rejected_without_chmod_or_state_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared"
            shared.mkdir()
            base = shared / "all-things-omarchy"
            base.mkdir(mode=0o755)
            path = base / "state.json"
            original = json.dumps(backend.empty_state()).encode()
            path.write_bytes(original)
            modes = (0o770, 0o777) + ((0o1777,) if os.getuid() != 0 else ())
            for mode in modes:
                shared.chmod(mode)
                with self.subTest(mode=oct(mode)), \
                        patch.object(backend, "state_path", return_value=path):
                    with self.assertRaisesRegex(RuntimeError, "writable ancestor"):
                        backend.load_state()
                    with self.assertRaisesRegex(RuntimeError, "writable ancestor"):
                        backend.save_state(backend.empty_state())
                    with self.assertRaisesRegex(RuntimeError, "writable ancestor"):
                        with backend.advisory_lock(backend.state_lock_path()):
                            pass
                    self.assertEqual(mode, shared.stat().st_mode & 0o7777)
                    self.assertEqual(0o755, base.stat().st_mode & 0o777)
                    self.assertEqual(original, path.read_bytes())
                    self.assertFalse(backend.state_lock_path().exists())

    def test_root_owned_sticky_ancestor_is_allowed_and_never_chmodded(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "sticky-root"
            shared.mkdir()
            shared.chmod(0o1777)
            shared_info = shared.stat()
            original_fstat = backend.os.fstat

            def root_owned_sticky(descriptor):
                info = original_fstat(descriptor)
                if (info.st_dev, info.st_ino) == (shared_info.st_dev, shared_info.st_ino):
                    return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
                return info

            path = shared / "all-things-omarchy" / "state.json"
            with patch.object(backend, "state_path", return_value=path), \
                    patch.object(backend.os, "fstat", side_effect=root_owned_sticky):
                state = backend.empty_state()
                state["readIds"] = ["news:keep"]
                backend.save_state(state)
                self.assertEqual(["news:keep"], backend.load_state()["readIds"])
                with backend.advisory_lock(backend.state_lock_path()):
                    pass
            self.assertEqual(0o1777, shared.stat().st_mode & 0o7777)
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)

    def test_foreign_owned_ancestor_is_rejected_before_creating_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory) / "foreign-owner"
            foreign.mkdir(mode=0o755)
            foreign_info = foreign.stat()
            original_fstat = backend.os.fstat

            def foreign_owned(descriptor):
                info = original_fstat(descriptor)
                if (info.st_dev, info.st_ino) == (foreign_info.st_dev, foreign_info.st_ino):
                    return SimpleNamespace(st_uid=os.getuid() + 100000, st_mode=info.st_mode)
                return info

            path = foreign / "all-things-omarchy" / "state.json"
            with patch.object(backend, "state_path", return_value=path), \
                    patch.object(backend.os, "fstat", side_effect=foreign_owned):
                with self.assertRaisesRegex(RuntimeError, "wrong owner"):
                    backend.save_state(backend.empty_state())
            self.assertFalse(path.parent.exists())
            self.assertEqual(0o755, foreign.stat().st_mode & 0o777)

    def test_load_and_mutation_reject_expanded_output_before_stdout_or_state_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.object(backend, "state_path", return_value=path):
                backend.save_state(backend.empty_state())
                original = path.read_bytes()
                for argv in (["Backend.py", "load"],
                             ["Backend.py", "mark-read", "news:keep"]):
                    output = io.StringIO()
                    with self.subTest(command=argv[1]), \
                            patch.object(sys, "argv", argv), \
                            patch.object(sys, "stdout", output), \
                            patch.object(backend, "MAX_OUTPUT_BYTES", len(original)):
                        with self.assertRaisesRegex(ValueError, "output limit"):
                            backend.main()
                    self.assertEqual("", output.getvalue())
                    self.assertEqual(original, path.read_bytes())

    def test_owner_directory_and_files_are_made_private_without_resetting_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "all-things-omarchy"
            base.mkdir(mode=0o755)
            path = base / "state.json"
            state = backend.empty_state()
            state["readIds"] = ["news:keep"]
            original = json.dumps(state).encode()
            path.write_bytes(original)
            path.chmod(0o644)
            with patch.object(backend, "state_path", return_value=path):
                self.assertEqual(["news:keep"], backend.load_state()["readIds"])
                self.assertEqual(original, path.read_bytes())
                self.assertEqual(0o700, base.stat().st_mode & 0o777)
                self.assertEqual(0o600, path.stat().st_mode & 0o777)
                with backend.advisory_lock(backend.state_lock_path()):
                    self.assertEqual(0o600, backend.state_lock_path().stat().st_mode & 0o777)

    def test_reads_bound_actual_bytes_instead_of_relying_on_stat_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_bytes(b"x" * 4096)
            original_fstat = backend.os.fstat

            def understated_size(descriptor):
                info = original_fstat(descriptor)
                return SimpleNamespace(st_uid=info.st_uid, st_mode=info.st_mode,
                                       st_nlink=info.st_nlink, st_size=1)

            with patch.object(backend, "state_path", return_value=path), \
                    patch.object(backend, "MAX_STATE_BYTES", 32), \
                    patch.object(backend.os, "fstat", side_effect=understated_size):
                with self.assertRaisesRegex(RuntimeError, "too large"):
                    backend.load_state()
            self.assertEqual(4096, path.stat().st_size)

    def test_state_display_lock_and_log_reject_symlinks_fifos_and_hardlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "state.json"
            outside = base / "outside"
            outside.write_bytes(b"must not change")
            for name in ("state.json", "display.json", ".state.lock", "update-launch.log"):
                target = base / name
                for kind in ("symlink", "fifo", "hardlink"):
                    with self.subTest(name=name, kind=kind), \
                            patch.object(backend, "state_path", return_value=path):
                        if kind == "symlink":
                            target.symlink_to(outside)
                        elif kind == "fifo":
                            os.mkfifo(target)
                        else:
                            os.link(outside, target)
                        try:
                            with self.assertRaises((RuntimeError, OSError)):
                                if name == "state.json":
                                    backend.load_state()
                                elif name == "display.json":
                                    backend.load_display()
                                elif name == ".state.lock":
                                    with backend.advisory_lock(target):
                                        pass
                                else:
                                    backend.launch_update()
                            if name in ("state.json", "display.json"):
                                with self.assertRaises((RuntimeError, OSError)):
                                    backend.write_state_file(target, backend.empty_state())
                            self.assertEqual(b"must not change", outside.read_bytes())
                        finally:
                            target.unlink()

    def test_symlink_directory_and_wrong_owner_are_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real = base / "real"
            real.mkdir()
            alias = base / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with patch.object(backend, "state_path", return_value=alias / "state.json"):
                with self.assertRaises((RuntimeError, OSError)):
                    backend.save_state(backend.empty_state())
            self.assertEqual([], list(real.iterdir()))
            with patch.object(backend, "state_path", return_value=real / "state.json"), \
                    patch.object(backend.os, "getuid", return_value=os.getuid() + 1):
                with self.assertRaisesRegex(RuntimeError, "wrong owner"):
                    backend.load_state()

    def test_lock_deadline_and_exception_release_for_state_and_display(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / ".state.lock"
            with backend.advisory_lock(lock):
                started = time.monotonic()
                with self.assertRaisesRegex(RuntimeError, "Timed out"):
                    with backend.advisory_lock(lock, timeout=0.1):
                        self.fail("lock unexpectedly acquired")
                self.assertLess(time.monotonic() - started, 0.5)
            with patch.object(backend, "state_path", return_value=lock.with_name("state.json")):
                for argv in (["Backend.py", "unknown"],
                             ["Backend.py", "display-save", "invalid", "800", "600"]):
                    with patch.object(sys, "argv", argv):
                        with self.assertRaises(ValueError):
                            backend.main()
                    with backend.advisory_lock(lock, timeout=0.1):
                        pass

    def test_parallel_cli_read_modify_writes_keep_all_changes_and_valid_display(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, XDG_STATE_HOME=directory, PYTHONDONTWRITEBYTECODE="1")
            base = Path(directory) / "all-things-omarchy"
            with patch.dict(os.environ, env):
                state = backend.empty_state()
                state["savedItems"] = [{"id": "news:keep", "kind": "news", "name": "Saved",
                                        "url": "https://omarchy.org/news/keep/"}]
                backend.save_state(state)
            commands = [["mark-read", "news:item-" + str(index)] for index in range(12)]
            commands += [["display-save", "window", str(800 + index), "600"] for index in range(4)]
            processes = [subprocess.Popen([sys.executable, str(BACKEND_PATH), *args],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                         for args in commands]
            try:
                for process in processes:
                    _, diagnostic = process.communicate(timeout=15)
                    self.assertEqual(0, process.returncode, diagnostic)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
            with patch.dict(os.environ, env):
                restored = backend.load_state()
                self.assertEqual({"news:item-" + str(index) for index in range(12)},
                                 set(restored["readIds"]))
                self.assertEqual(["news:keep"], [item["id"] for item in restored["savedItems"]])
                self.assertEqual(600, backend.load_display()["height"])
                self.assertIn(backend.load_display()["width"], range(800, 804))
                self.assertEqual(0o600, (base / "display.json").stat().st_mode & 0o777)

    def test_display_save_subprocess_waits_for_shared_state_transaction_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, XDG_STATE_HOME=directory)
            base = Path(directory) / "all-things-omarchy"
            process = None
            try:
                with backend.advisory_lock(base / ".state.lock"):
                    process = subprocess.Popen([sys.executable, str(BACKEND_PATH), "display-save",
                                                "window", "900", "650"], env=env,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    time.sleep(0.15)
                    self.assertIsNone(process.poll())
                    self.assertFalse((base / "display.json").exists())
                output, diagnostic = process.communicate(timeout=5)
                self.assertEqual(0, process.returncode, diagnostic)
                self.assertEqual(900, json.loads(output)["width"])
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait()


class ThumbnailBoundaryTests(unittest.TestCase):
    URL = "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"

    @staticmethod
    def png(width=32, height=24):
        import zlib

        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data)))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * width * 3) * height))
                + chunk(b"IEND", b""))

    def test_png_jpeg_webp_dimensions_and_bombs_or_unsupported_data(self):
        self.assertEqual((32, 24), backend.thumbnail_dimensions(self.png()))
        jpeg = b"\xff\xd8\xff\xc0\0\x0b\x08\0\x18\0\x20\x01\x01\x11\0\xff\xda"
        self.assertEqual((32, 24), backend.thumbnail_dimensions(jpeg))
        vp8l = b"\x2f" + struct.pack("<I", 31 | (23 << 14))
        payload = b"VP8L" + struct.pack("<I", len(vp8l)) + vp8l + b"\0"
        webp = b"RIFF" + struct.pack("<I", len(payload) + 4) + b"WEBP" + payload
        self.assertEqual((32, 24), backend.thumbnail_dimensions(webp))
        for body in (self.png(4097, 1), self.png(4096, 4096), b"<svg/>",
                     b"GIF89a" + b"\xff" * 20, b"\xff\xd8", webp[:-1],
                     self.png()[:-12], jpeg.replace(b"\0\x18\0\x20", b"\xff\xff\xff\xff")):
            with self.subTest(prefix=body[:20]), self.assertRaises(ValueError):
                backend.thumbnail_dimensions(body)

    def test_local_theme_previews_share_dimension_and_byte_limits_and_surface_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            theme = home / ".config/omarchy/themes/safe-theme"
            theme.mkdir(parents=True)
            preview = theme / "preview.png"
            current = subprocess.CompletedProcess([], 0, "Safe Theme\n", "")
            with patch.object(backend.Path, "home", return_value=home), \
                    patch.dict(os.environ, {"OMARCHY_PATH": str(base / "stock")}), \
                    patch.object(backend, "system_command", return_value=(current, "")):
                preview.write_bytes(self.png())
                self.assertEqual(preview.as_uri(), backend.theme_status()["previews"]["Safe Theme"])
                self.assertEqual("", backend.theme_status()["warning"])
                preview.write_bytes(self.png(4097, 1))
                response = backend.theme_status()
                self.assertEqual({}, response["previews"])
                self.assertIn("dimensions", response["warning"])
                preview.write_bytes(b"x" * 65)
                with patch.object(backend, "MAX_LOCAL_PREVIEW_BYTES", 64):
                    response = backend.theme_status()
                self.assertIn("size limit", response["warning"])
                preview.unlink()
                (theme / "preview.gif").write_bytes(b"GIF89a" + b"\xff" * 20)
                response = backend.theme_status()
                self.assertEqual({}, response["previews"])
                self.assertIn("unsupported", response["warning"])
                backgrounds = theme / "backgrounds"
                backgrounds.mkdir()
                background = backgrounds / "safe.png"
                background.write_bytes(self.png())
                response = backend.theme_status()
                self.assertEqual(background.as_uri(), response["previews"]["Safe Theme"])
                self.assertIn("unsupported", response["warning"])

    def test_cache_returns_only_local_uri_reuses_verified_file_and_bounds_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            result = subprocess.CompletedProcess([], 0, self.png(), b"")
            with patch.object(backend, "state_path", return_value=path), \
                    patch.object(backend, "bounded_run", return_value=result) as run, \
                    patch.object(backend, "MAX_CACHE_FILES", 2), \
                    patch.object(backend, "MAX_CACHE_BYTES", len(self.png()) * 2):
                response = backend.thumbnail(self.URL)
                self.assertTrue(response["url"].startswith("file://"))
                local = Path(backend.urllib.parse.unquote(backend.urllib.parse.urlsplit(response["url"]).path))
                self.assertEqual(self.png(), local.read_bytes())
                self.assertEqual(0o600, local.stat().st_mode & 0o777)
                self.assertEqual(0o700, local.parent.stat().st_mode & 0o777)
                self.assertEqual(response, backend.thumbnail(self.URL))
                self.assertEqual(1, run.call_count)
                backend.thumbnail(self.URL.replace("abcdefghijk", "ABCDEFGHIJK"))
                backend.thumbnail(self.URL.replace("abcdefghijk", "01234567890"))
                self.assertEqual(2, len(list(local.parent.glob("*.img"))))
                self.assertFalse(local.exists())

    def test_cache_refuses_symlinks_and_unexpected_files_without_removing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cache = base / "thumbnails"
            cache.mkdir()
            name = backend.hashlib.sha256(self.URL.encode()).hexdigest() + ".img"
            outside = base / "user-image"
            outside.write_bytes(self.png())
            path = cache / name
            path.symlink_to(outside)
            with patch.object(backend, "state_path", return_value=base / "state.json"), \
                    patch.object(backend, "bounded_run") as run:
                with self.assertRaisesRegex(RuntimeError, "private regular file"):
                    backend.thumbnail(self.URL)
                run.assert_not_called()
                self.assertTrue(path.is_symlink())
                path.unlink()
                path.write_bytes(self.png())
                arbitrary = cache / "user-photo.png"
                arbitrary.write_bytes(b"keep me")
                with self.assertRaisesRegex(RuntimeError, "unexpected file"):
                    backend.thumbnail(self.URL)
                self.assertEqual(b"keep me", arbitrary.read_bytes())
                self.assertEqual(self.png(), outside.read_bytes())
                run.assert_not_called()

    def test_download_failures_oversized_images_and_unsafe_urls_never_create_cache_entries(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend, "state_path", return_value=Path(directory) / "state.json"):
            for url in ("file:///etc/passwd", "http://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg",
                        self.URL + "?tracking=1", self.URL + "#fragment",
                        "https://evil.example/image.png", "assets/img/plugins/image.webp"):
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, "not allowed"):
                    backend.thumbnail(url)
            for result, expected in (
                    (subprocess.CompletedProcess([], 1, b"", b'{"error":"remote failure"}'), "remote failure"),
                    (subprocess.CompletedProcess([], 0, b"x" * (backend.MAX_THUMBNAIL_BYTES + 1), b""), "size limit"),
                    (subprocess.CompletedProcess([], 0, self.png(4097, 1), b""), "dimensions"),
                    (subprocess.CompletedProcess([], 0, b"<svg/>", b""), "unsupported")):
                with self.subTest(expected=expected), \
                        patch.object(backend, "bounded_run", return_value=result), \
                        self.assertRaisesRegex((ValueError, RuntimeError), expected):
                    backend.thumbnail(self.URL)
            with patch.object(backend, "bounded_run",
                              side_effect=subprocess.TimeoutExpired("download", 15)):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    backend.thumbnail(self.URL)
            self.assertEqual([], list(Path(directory).glob("thumbnails/*.img")))

    def test_redirects_enforce_scheme_host_path_credentials_and_query(self):
        handler = backend.ThumbnailRedirectHandler()
        request = backend.urllib.request.Request(self.URL)
        valid = self.URL.replace("abcdefghijk", "ABCDEFGHIJK")
        self.assertEqual(valid, handler.redirect_request(request, None, 302, "Found", {}, valid).full_url)
        for url in ("http://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg",
                    "https://omarchy.org/news/image.png", self.URL + "?redirect=1",
                    "https://user@i.ytimg.com/vi/abcdefghijk/mqdefault.jpg",
                    "https://i.ytimg.com/not-an-image.jpg"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "allowlist"):
                handler.redirect_request(request, None, 302, "Found", {}, url)

    def test_bounded_download_counts_actual_stream_bytes_and_checks_final_url(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = self.URL
        response.headers = {"Content-Length": "1"}
        response.read1.side_effect = [b"a" * 32, b"b" * 33]
        opener = Mock()
        opener.open.return_value = response
        with patch.object(backend.urllib.request, "build_opener", return_value=opener), \
                patch.object(backend, "MAX_THUMBNAIL_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "size limit"):
                backend.download_thumbnail_bytes(self.URL)
            response.geturl.return_value = "https://evil.example/image.png"
            with self.assertRaisesRegex(ValueError, "allowlist"):
                backend.download_thumbnail_bytes(self.URL)

    def test_cli_invalid_thumbnail_emits_explicit_json_stderr(self):
        result = subprocess.run([sys.executable, str(BACKEND_PATH), "thumbnail",
                                 "https://evil.example/tracking.png"],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("not allowed", json.loads(result.stderr)["error"])


if __name__ == "__main__":
    unittest.main()
