import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


BACKEND_PATH = Path(__file__).resolve().parents[1] / "Backend.py"
SPEC = importlib.util.spec_from_file_location("all_things_backend", BACKEND_PATH)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class TextTests(unittest.TestCase):
    def test_clean_text_removes_markup_and_control_characters(self):
        self.assertEqual(
            "Omarchy updates",
            backend.clean_text("<b>Omarchy</b> updates\u0000"),
        )

    def test_clean_text_bounds_untrusted_text(self):
        self.assertEqual("safe", backend.clean_text("safe" + "x" * 100, 4))


class CatalogTests(unittest.TestCase):
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
            stock_preview.write_bytes(b"stock")
            local_preview = user_theme / "preview.png"
            local_preview.write_bytes(b"local")
            with patch.object(backend.Path, "home", return_value=home), \
                    patch.dict(os.environ, {"OMARCHY_PATH": str(base / "omarchy")}):
                self.assertEqual(local_preview.as_uri(), backend.theme_preview("Tokyo Night"))
                local_preview.unlink()
                outside = base / "outside.png"
                outside.write_bytes(b"outside")
                local_preview.symlink_to(outside)
                background = user_theme / "backgrounds" / "background.jpg"
                background.parent.mkdir()
                background.write_bytes(b"background")
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
                patch.object(backend, "theme_preview", side_effect=lambda name: "file:///preview.png"
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
        with patch.object(backend.subprocess, "run",
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
                patch.object(backend.subprocess, "run", return_value=result) as run:
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


if __name__ == "__main__":
    unittest.main()
