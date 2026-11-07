#!/usr/bin/env python3

import hashlib
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from itertools import permutations
from pathlib import Path


PLUGIN_CATALOG = "https://plugins.omarchy.org/catalog.json"
NEWS_FEED = "https://omarchy.org/news/rss.xml"
NEWS_HOME = "https://omarchy.org/news/"
PLUGIN_HOME = "https://plugins.omarchy.org/"
THEME_HOME = "https://omarchy.org/themes/"
RELEASES_API = "https://api.github.com/repos/omacom/omarchy/releases?per_page=100"
MANUAL_INDEX = "https://omarchy.org/data/search-index.json"
MANUAL_HOME = "https://omarchy.org/manual/"
HOTKEYS_HOME = "https://omarchy.org/manual/hotkeys/"
COMMUNITY_HOME = "https://omarchy.deepakness.com/resources"
COMMUNITY_DATA = "https://raw.githubusercontent.com/deepakness/omarchy-hub/main/data/resources.json"
EVENTS_HOME = "https://omarchy.org/meetups/"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_ITEMS_PER_SOURCE = 10000
MAX_SAVED_ITEMS = 500
MAX_KNOWN_IDS = 20000
MAX_TEXT_LENGTH = 1000
PLUGIN_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_RANGE_FILTERS = {
    "day": 2,
    "week": 3,
    "month": 4,
    "all": "",
}
DEFAULT_SETTINGS = {
    "refreshOnOpen": True,
    "pluginsLimit": 50,
    "themesLimit": 50,
    "videosLimit": 100,
    "newsLimit": 50,
    "youtubeRange": "all",
    "sortOrder": "recent",
}
DEFAULT_DISPLAY = {"mode": "docked", "width": 0, "height": 0}
DISPLAY_MODES = {"docked", "window", "maximized"}
SETTING_VALUES = {
    "refreshOnOpen": {"true", "false"},
    "pluginsLimit": {"20", "50", "100"},
    "themesLimit": {"20", "50", "100"},
    "videosLimit": {"50", "100", "150"},
    "newsLimit": {"20", "50", "100"},
    "youtubeRange": set(YOUTUBE_RANGE_FILTERS),
    "sortOrder": {"recent", "title"},
}
SOURCE_KEYS = ("plugins", "themes", "videos", "news", "releases", "manual", "hotkeys",
               "community", "events")
FILTER_SECTIONS = SOURCE_KEYS + ("saved",)
DASHBOARD_PANELS = ("system", "catchUp", "events", "saved")
DEFAULT_SETTINGS.update({
    "showPreviews": True, "density": "comfortable", "markReadOnOpen": True,
    "systemCheckOnOpen": True,
    "dashboardOrder": ",".join(DASHBOARD_PANELS), "dashboardNewOnly": False,
    "catchUpLimit": 8, "eventsLimit": 3, "savedLimit": 4,
    **{"refresh_" + section: True for section in SOURCE_KEYS},
    **{"remember_" + section: True for section in FILTER_SECTIONS},
    **{"dashboard_" + panel: True for panel in DASHBOARD_PANELS},
    **{"dashboardSource_" + section: True for section in
       ("plugins", "themes", "videos", "news", "releases", "community")},
})
BOOLEAN_SETTINGS = {key for key, value in DEFAULT_SETTINGS.items() if isinstance(value, bool)}
SETTING_VALUES.update({key: {"true", "false"} for key in BOOLEAN_SETTINGS})
SETTING_VALUES.update({
    "density": {"compact", "comfortable"},
    "dashboardOrder": {",".join(order).lower() for order in permutations(DASHBOARD_PANELS)},
    "catchUpLimit": {"4", "8", "12", "16"},
    "eventsLimit": {"1", "3", "5"},
    "savedLimit": {"2", "4", "8"},
})
# Settings values are normalized to lowercase on disk and at the CLI boundary.
DEFAULT_SETTINGS["dashboardOrder"] = DEFAULT_SETTINGS["dashboardOrder"].lower()
SETTING_GROUPS = {
    "general": {"showPreviews", "density", "markReadOnOpen"},
    "dashboard": {key for key in DEFAULT_SETTINGS if key.startswith("dashboard")
                  or key in ("catchUpLimit", "eventsLimit", "savedLimit")},
    "refresh": {"refreshOnOpen", "systemCheckOnOpen"} |
               {"refresh_" + section for section in SOURCE_KEYS},
    **{section: {"remember_" + section} | (
        {"refresh_" + section} if section in SOURCE_KEYS else set()) |
        ({"videosLimit"} if section == "videos" else set())
       for section in FILTER_SECTIONS},
}
SOURCE_ERRORS = {
    "plugins": "Could not load the plugin marketplace catalog.",
    "themes": "Could not load the official Omarchy themes page.",
    "videos": "Could not search YouTube.",
    "news": "Could not load official Omarchy News.",
    "releases": "Could not load Omarchy releases.",
    "manual": "Could not load the Omarchy manual index.",
    "hotkeys": "Could not load Omarchy hotkeys.",
    "community": "Could not load community resources.",
    "events": "Could not load Omarchy meetups.",
}
REDIRECT_HOSTS = {
    "plugins.omarchy.org",
    "omarchy.org",
    "www.omarchy.org",
    "api.github.com",
    "raw.githubusercontent.com",
}


class PlainTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def clean_text(value, limit=MAX_TEXT_LENGTH):
    if not isinstance(value, str):
        return ""
    parser = PlainTextParser()
    try:
        parser.feed(html.unescape(value))
        value = " ".join(parser.parts)
    except (ValueError, AssertionError):
        value = html.unescape(value)
    value = "".join(char for char in value if char.isprintable())
    return " ".join(value.split())[:limit]


def clean_plain_text(value, limit=MAX_TEXT_LENGTH):
    if not isinstance(value, str):
        return ""
    value = "".join(char if char.isprintable() else " " if char.isspace() else "" for char in value)
    return " ".join(value.split())[:limit]


def state_path():
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        base = Path(state_home)
    else:
        base = Path.home() / ".local" / "state"
    return base / "all-things-omarchy" / "state.json"


def empty_state():
    return {
        "version": 1,
        "baselineEstablished": False,
        "knownIds": [],
        "newIds": [],
        "readIds": [],
        "savedItems": [],
        "settings": dict(DEFAULT_SETTINGS),
        "sources": {},
        "filters": {},
    }


def load_state():
    path = state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_state()
    except OSError as error:
        raise RuntimeError("Could not read the local plugin state.") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("The local plugin state is invalid; move or repair its state file.") from error
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("The local plugin state has an unsupported format.")

    state = empty_state()
    state["baselineEstablished"] = value.get("baselineEstablished") is True
    state["knownIds"] = valid_id_list(value.get("knownIds"), MAX_KNOWN_IDS)
    state["newIds"] = valid_id_list(value.get("newIds"), MAX_KNOWN_IDS)
    state["readIds"] = valid_id_list(value.get("readIds"), MAX_KNOWN_IDS)
    state["savedItems"] = normalize_saved(value.get("savedItems"))
    state["settings"].update(valid_settings(value.get("settings")))
    state["filters"] = valid_filters(value.get("filters"))
    sources = value.get("sources")
    if isinstance(sources, dict):
        for key in SOURCE_KEYS:
            source = sources.get(key)
            if not isinstance(source, dict):
                continue
            items = source.get("items")
            state["sources"][key] = {
                "items": normalize_items(key, items) if isinstance(items, list) else [],
                "fetchedAt": valid_timestamp(source.get("fetchedAt")),
                "message": clean_text(source.get("message"), 240),
                "provider": clean_text(source.get("provider"), 60),
            }
    return state


def write_state_file(path, state):
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=str(path.parent))
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=True, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    except OSError as error:
        raise RuntimeError("Could not save the local plugin state.") from error


def save_state(state):
    write_state_file(state_path(), state)


def validate_display(value):
    if (not isinstance(value, dict) or not isinstance(value.get("mode"), str)
            or value["mode"] not in DISPLAY_MODES):
        raise ValueError("The saved display mode is invalid.")
    width, height = value.get("width"), value.get("height")
    if (type(width) is not int or type(height) is not int
            or not (0 <= width <= 16384 and 0 <= height <= 16384)
            or ((width == 0) != (height == 0))):
        raise ValueError("The saved window size is invalid.")
    return {"mode": value["mode"], "width": width, "height": height}


def load_display():
    path = state_path().with_name("display.json")
    try:
        with path.open("rb") as source:
            raw = source.read(4097)
    except FileNotFoundError:
        return dict(DEFAULT_DISPLAY)
    except OSError as error:
        raise RuntimeError("Could not read the saved display preference.") from error
    if len(raw) > 4096:
        raise ValueError("The saved display preference is too large.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The saved display preference is invalid.") from error
    return validate_display(value)


def save_display(value):
    display = validate_display(value)
    write_state_file(state_path().with_name("display.json"), display)
    return display


def valid_timestamp(value, future=False):
    if isinstance(value, bool):
        return 0
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if timestamp < 0 or timestamp > (4102444800 if future else int(time.time()) + 86400):
        return 0
    return timestamp


def valid_id_list(values, limit):
    if not isinstance(values, list):
        return []
    result = []
    found = set()
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r"[a-z]+:[A-Za-z0-9._-]{1,180}", value):
            continue
        if value in found:
            continue
        found.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def valid_settings(value):
    if not isinstance(value, dict):
        return {}
    settings = {}
    for key, allowed in SETTING_VALUES.items():
        candidate = value.get(key)
        normalized = str(candidate).lower()
        if key not in value or normalized not in allowed:
            continue
        if key in BOOLEAN_SETTINGS:
            settings[key] = normalized == "true"
        elif key.endswith("Limit"):
            settings[key] = int(normalized)
        else:
            settings[key] = normalized
    return settings


def valid_filters(value, strict=False):
    def filter_text(text):
        return "".join(char for char in text if char.isprintable())

    def invalid():
        if strict:
            raise ValueError("Invalid saved filters.")
        return {}

    if not isinstance(value, dict) or len(value) > len(FILTER_SECTIONS):
        return invalid()
    result = {}
    for section, entry in value.items():
        if section not in FILTER_SECTIONS or not isinstance(entry, dict):
            return invalid()
        query = entry.get("query", "")
        terms = entry.get("terms", [])
        date_range = entry.get("range", "all")
        if not isinstance(query, str) or len(query) > 240 or not isinstance(terms, list) \
                or len(terms) > 16 or any(not isinstance(term, str) or len(term) > 240 for term in terms) \
                or date_range not in ("all", "today", "week", "month"):
            return invalid()
        result[section] = {"query": filter_text(query),
                           "terms": [filter_text(term) for term in terms],
                           "range": date_range}
    return result


def safe_https_url(value, hosts=None):
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError:
        return ""
    allowed = hosts or {"github.com"}
    try:
        port = parsed.port
    except ValueError:
        return ""
    if (parsed.scheme != "https" or parsed.hostname not in allowed
            or parsed.username or parsed.password or port not in (None, 443)):
        return ""
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


def safe_external_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return ""
    labels = host.split(".")
    if (parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443)
            or len(host) > 253 or len(labels) < 2
            or not re.fullmatch(r"[a-z]{2,63}", labels[-1])
            or labels[-1] in {"local", "localhost", "internal", "test", "invalid"}
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                   for label in labels)):
        return ""
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def safe_manual_url(value):
    base = safe_https_url(value, {"omarchy.org", "www.omarchy.org"})
    if not base:
        return ""
    parsed = urllib.parse.urlsplit(value)
    if (parsed.query or not re.fullmatch(r"/manual/(?:[a-z0-9-]+/)?", parsed.path)
            or (parsed.fragment and not re.fullmatch(r"[a-z0-9_-]{1,120}", parsed.fragment))):
        return ""
    return base + ("#" + parsed.fragment if parsed.fragment else "")


def safe_thumbnail(kind, value):
    hosts = {
        "plugins": {"plugins.omarchy.org"},
        "themes": {"omarchy.org", "www.omarchy.org", "cdn.themes.omarchy.org",
                   "pub-98465b4520f24f9a8f162c4f722a293f.r2.dev"},
        "videos": {"i.ytimg.com"},
        "news": {"omarchy.org", "www.omarchy.org"},
        "events": {"omarchy.org", "www.omarchy.org"},
    }
    if kind not in hosts or not isinstance(value, str):
        return ""
    if kind == "plugins":
        value = urllib.parse.urljoin(PLUGIN_HOME, value)
    elif kind == "themes":
        value = urllib.parse.urljoin(THEME_HOME, value)
    elif kind == "events":
        value = urllib.parse.urljoin(EVENTS_HOME, value)
    url = safe_https_url(value, hosts[kind])
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    if parsed.query or ".." in parsed.path:
        return ""
    patterns = {
        "plugins": r"/assets/img/plugins/[A-Za-z0-9._-]+\.(?:webp|png|jpe?g)",
        "themes": (r"/assets/themes/[A-Za-z0-9._-]+\.webp"
                   if parsed.hostname in {"omarchy.org", "www.omarchy.org"}
                   else r"/v1/previews/[A-Za-z0-9._-]+/[0-9a-f]{40}/(?:480|1200)\.webp"),
        "videos": r"/vi/[A-Za-z0-9_-]{11}/mqdefault\.jpg",
        "news": r"/news/[A-Za-z0-9_./-]+\.(?:webp|png|jpe?g)",
        "events": r"/images/meetups/evt-[A-Za-z0-9]+-full\.webp",
    }
    return url if re.fullmatch(patterns[kind], parsed.path, re.IGNORECASE) else ""


def valid_item(item):
    if not isinstance(item, dict):
        return None
    item_id = item.get("id")
    kind = item.get("kind")
    url = item.get("url")
    if not isinstance(item_id, str) or not re.fullmatch(r"[a-z]+:[A-Za-z0-9._-]{1,180}", item_id):
        return None
    if kind not in SOURCE_KEYS:
        return None
    parsed_url = (safe_manual_url(url) if kind in ("manual", "hotkeys") else
                  safe_external_url(url) if kind in ("community", "events") else safe_https_url(url, {
        "plugins.omarchy.org", "themes.omarchy.org", "github.com",
        "www.youtube.com", "youtube.com", "omarchy.org", "www.omarchy.org",
    }))
    if not parsed_url:
        return None
    text_cleaner = clean_plain_text if kind in ("manual", "hotkeys") else clean_text
    name = text_cleaner(item.get("name"), 240)
    if not name:
        return None
    timestamp = valid_timestamp(item.get("timestamp"), future=kind == "events")
    return {
        "id": item_id,
        "kind": kind,
        "name": name,
        "summary": text_cleaner(item.get("summary"), 600),
        "searchText": clean_plain_text(item.get("searchText"), 6000) if kind in ("manual", "community") else "",
        "author": text_cleaner(item.get("author"), 120),
        "url": parsed_url,
        "timestamp": timestamp,
        "source": text_cleaner(item.get("source"), 100),
        "thumbnail": safe_thumbnail(kind, item.get("thumbnail")),
        "isNew": item.get("isNew") is True,
        "isRead": item.get("isRead") is True,
        "isSaved": item.get("isSaved") is True,
    }


def normalize_items(kind, rows):
    if not isinstance(rows, list):
        return []
    result = []
    found = set()
    for row in rows:
        item = valid_item(row)
        if not item or item["kind"] != kind or item["id"] in found:
            continue
        found.add(item["id"])
        result.append(item)
    if kind == "events":
        now = time.time()
        result.sort(key=lambda item: (0, item["timestamp"]) if item["timestamp"] >= now
                    else (1, -item["timestamp"]))
    elif kind not in ("themes", "manual", "hotkeys", "community"):
        result.sort(key=lambda item: item["timestamp"], reverse=True)
    return result[:MAX_ITEMS_PER_SOURCE]


def normalize_saved(rows):
    result = []
    found = set()
    if not isinstance(rows, list):
        return result
    for row in rows[:MAX_SAVED_ITEMS]:
        item = valid_item(row)
        if not item or item["id"] in found:
            continue
        item["isSaved"] = True
        found.add(item["id"])
        result.append(item)
    return result


class RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        try:
            target = urllib.parse.urlsplit(new_url)
        except ValueError:
            return None
        if target.scheme != "https" or target.hostname not in REDIRECT_HOSTS:
            return None
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch_bytes(url, max_bytes=MAX_RESPONSE_BYTES, timeout=15):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AllThingsOmarchy/0.1 (Omarchy shell plugin)"},
    )
    opener = urllib.request.build_opener(RestrictedRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in REDIRECT_HOSTS:
                raise ValueError("The source redirected outside its allowlist.")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError("The source response exceeded the size limit.")
            body = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError("The source returned HTTP " + str(error.code) + ".") from error
    except urllib.error.URLError as error:
        raise RuntimeError("The source could not be reached.") from error
    if len(body) > max_bytes:
        raise ValueError("The source response exceeded the size limit.")
    return body


def fetch_json(url):
    try:
        value = json.loads(fetch_bytes(url).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The source returned invalid JSON.") from error
    return value


def item_timestamp(value):
    if not isinstance(value, str) or not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None and len(value) != 10:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return valid_timestamp(parsed.timestamp())
    except (ValueError, OverflowError):
        try:
            parsed = parsedate_to_datetime(value)
            return valid_timestamp(parsed.timestamp())
        except (TypeError, ValueError, OverflowError):
            return 0


def normalize_plugins(payload):
    rows = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("The plugin catalog has an unexpected format.")
    result = []
    found = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        plugin_id = row.get("id")
        if not isinstance(plugin_id, str) or not PLUGIN_ID.fullmatch(plugin_id) or plugin_id in found:
            continue
        name = clean_text(row.get("name"), 240)
        if not name:
            continue
        found.add(plugin_id)
        url = PLUGIN_HOME + "plugin.html?id=" + urllib.parse.quote(plugin_id, safe="")
        result.append({
            "id": "plugin:" + plugin_id,
            "kind": "plugins",
            "name": name,
            "summary": clean_text(row.get("description"), 600),
            "author": clean_text(row.get("author"), 120),
            "url": url,
            "timestamp": item_timestamp(row.get("listedAt") or row.get("addedAt")),
            "source": clean_text(row.get("category") or row.get("kind") or "Plugin marketplace", 100),
            "thumbnail": (safe_thumbnail("plugins", row.get("previewThumbnail"))
                          or safe_thumbnail("plugins", row.get("previewImage"))),
        })
    result.sort(key=lambda item: item["timestamp"], reverse=True)
    return result[:MAX_ITEMS_PER_SOURCE]


def theme_repo_key(value):
    repo = safe_https_url(value, {"github.com"})
    if not repo:
        return ""
    parsed = urllib.parse.urlsplit(repo)
    if parsed.query or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", parsed.path):
        return ""
    return parsed.path.rstrip("/").removesuffix(".git").lower()


class ThemePageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.card = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.card = {"url": attrs.get("href", ""), "thumbnail": "", "text": []}
        elif tag == "img" and self.card is not None:
            self.card["thumbnail"] = safe_thumbnail("themes", attrs.get("src"))

    def handle_data(self, data):
        if self.card is not None:
            self.card["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.card is not None:
            if self.card["thumbnail"]:
                self.cards.append(self.card)
            self.card = None


def normalize_themes(payload):
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("The official themes page is not valid UTF-8.") from error
    parser = ThemePageParser()
    parser.feed(page)
    result = []
    seen = set()
    for card in parser.cards:
        repo_key = theme_repo_key(card["url"])
        name = clean_text(" ".join(card["text"]), 240)
        if not repo_key or not name or repo_key in seen:
            continue
        seen.add(repo_key)
        digest = hashlib.sha256(repo_key.encode("utf-8")).hexdigest()[:32]
        result.append({
            "id": "theme:" + digest,
            "kind": "themes",
            "name": name,
            "summary": "",
            "author": clean_text(urllib.parse.urlsplit(card["url"]).path.strip("/").split("/")[0], 120),
            "url": safe_https_url(card["url"], {"github.com"}),
            "timestamp": 0,
            "source": "Omarchy themes",
            "thumbnail": card["thumbnail"],
        })
        if len(result) >= MAX_ITEMS_PER_SOURCE:
            break
    if not result:
        raise ValueError("The official themes page has no recognized theme cards.")
    return result


def normalize_community(payload):
    if not isinstance(payload, list):
        raise ValueError("The community resources catalog has an unexpected format.")
    result = []
    seen = set()
    for row in payload[:MAX_ITEMS_PER_SOURCE]:
        if not isinstance(row, dict):
            continue
        resource_id = row.get("id")
        if not isinstance(resource_id, str) or not re.fullmatch(r"[0-9]{1,10}", resource_id):
            continue
        url = safe_external_url(row.get("link"))
        name = clean_text(row.get("name"), 240)
        if not url or not name or resource_id in seen:
            continue
        seen.add(resource_id)
        tags = row.get("tags")
        tags = tags[:50] if isinstance(tags, list) else []
        result.append({
            "id": "community:" + resource_id, "kind": "community", "name": name,
            "summary": clean_text(row.get("description"), 600),
            "searchText": " ".join(clean_plain_text(tag, 80) for tag in tags),
            "author": clean_text(row.get("author"), 120), "url": url, "timestamp": 0,
            "source": clean_text(row.get("category"), 100), "thumbnail": "",
        })
    if not result:
        raise ValueError("The community resources catalog has no recognized entries.")
    result.sort(key=lambda item: int(item["id"].split(":")[1]), reverse=True)
    return result


class MeetupPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.card = None
        self.paragraph = None
        self.heading = None
        self.in_time = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and re.fullmatch(r"meetup-evt-[A-Za-z0-9]{1,80}", attrs.get("id", "")):
            self.card = {"id": attrs["id"][7:], "paragraphs": [], "name": ""}
        elif self.card is not None:
            if tag == "a":
                self.card["url"] = attrs.get("href", "")
            elif tag == "img":
                self.card["thumbnail"] = attrs.get("src", "")
                self.card["alt"] = attrs.get("alt", "")
            elif tag == "time":
                self.in_time = True
                self.card["date"] = attrs.get("datetime", "")
            elif tag == "p":
                self.paragraph = []
            elif tag == "h3":
                self.heading = []

    def handle_data(self, data):
        if self.card is None:
            return
        if self.paragraph is not None and not self.in_time:
            self.paragraph.append(data)
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag == "time":
            self.in_time = False
        elif tag == "p" and self.paragraph is not None:
            self.card["paragraphs"].append(clean_plain_text(" ".join(self.paragraph), 300).strip(" ·"))
            self.paragraph = None
        elif tag == "h3" and self.heading is not None:
            self.card["name"] = clean_plain_text(" ".join(self.heading), 240)
            self.heading = None
        elif tag == "li":
            self.cards.append(self.card)
            self.card = None
            self.paragraph = None
            self.heading = None
            self.in_time = False


def normalize_events(payload):
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("The meetups page is not valid UTF-8.") from error
    parser = MeetupPageParser()
    parser.feed(page)
    result = []
    seen = set()
    for card in parser.cards[:MAX_ITEMS_PER_SOURCE]:
        try:
            date = datetime.fromisoformat(card.get("date", "").replace("Z", "+00:00"))
            timestamp = valid_timestamp(date.timestamp(), future=True) if date.utcoffset() is not None else 0
        except (ValueError, OverflowError, OSError):
            continue
        event_id = card["id"]
        url = safe_external_url(card.get("url"))
        paragraphs = [part for part in card["paragraphs"] if part]
        name = clean_plain_text(card.get("name") or card.get("alt") or
                                (paragraphs[-1] if paragraphs else ""), 240)
        location = next((part for part in paragraphs if part != name), "")
        if not timestamp or not url or not name or event_id in seen:
            continue
        seen.add(event_id)
        result.append({
            "id": "event:" + event_id, "kind": "events", "name": name,
            "summary": location, "author": "", "url": url, "timestamp": timestamp,
            "source": "Omarchy meetups", "thumbnail": safe_thumbnail("events", card.get("thumbnail")),
        })
    if not result:
        raise ValueError("The meetups page has no recognized event cards.")
    return normalize_items("events", result)


def reconcile_theme_ids(rows, state):
    previous = state["savedItems"] + state["sources"].get("themes", {}).get("items", [])
    by_repo = {}
    for item in previous:
        if item.get("kind") == "themes":
            key = theme_repo_key(item.get("url"))
            if key:
                by_repo.setdefault(key, item["id"])
    used = set()
    for item in rows:
        old_id = by_repo.get(theme_repo_key(item["url"]))
        if old_id and old_id not in used:
            item["id"] = old_id
        used.add(item["id"])
    return rows


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element, names):
    wanted = set(names)
    for child in list(element):
        if local_name(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


class NewsImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "img":
            value = dict(attrs).get("src")
            if value:
                self.images.append(value)


def news_thumbnail(entry, article_url):
    candidates = []
    for child in list(entry):
        name = local_name(child.tag)
        if name in ("thumbnail", "content") and child.attrib.get("url"):
            candidates.append(child.attrib["url"])
        elif name == "enclosure" and child.attrib.get("type", "").lower().startswith("image/"):
            candidates.append(child.attrib.get("url", ""))
    parser = NewsImageParser()
    for child in list(entry):
        if local_name(child.tag) in ("encoded", "description", "content") and child.text:
            parser.feed(child.text)
    candidates.extend(parser.images)
    for candidate in candidates:
        url = safe_thumbnail("news", urllib.parse.urljoin(article_url, candidate))
        if url:
            return url
    return ""


def normalize_news(payload):
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError("The official news feed is not valid XML.") from error
    entries = [item for item in root.iter() if local_name(item.tag) in ("item", "entry")]
    result = []
    found = set()
    for entry in entries[:MAX_ITEMS_PER_SOURCE * 2]:
        title = clean_text(child_text(entry, {"title"}), 240)
        if not title:
            continue
        url = child_text(entry, {"link"})
        for child in list(entry):
            if local_name(child.tag) == "link" and child.attrib.get("href"):
                url = child.attrib["href"]
                break
        url = safe_https_url(url, {"omarchy.org", "www.omarchy.org"})
        if not url:
            url = NEWS_HOME
        guid = child_text(entry, {"guid", "id"}) or url + "\n" + title
        digest = hashlib.sha256(guid.encode("utf-8")).hexdigest()[:32]
        item_id = "news:" + digest
        if item_id in found:
            continue
        found.add(item_id)
        summary = child_text(entry, {"description", "summary", "content"})
        published = child_text(entry, {"pubdate", "published", "updated", "date"})
        result.append({
            "id": item_id,
            "kind": "news",
            "name": title,
            "summary": clean_text(summary, 600),
            "author": clean_text(child_text(entry, {"author", "creator"}), 120),
            "url": url,
            "timestamp": item_timestamp(published),
            "source": "Omarchy News",
            "thumbnail": news_thumbnail(entry, url),
        })
        if len(result) >= MAX_ITEMS_PER_SOURCE:
            break
    if not entries:
        raise ValueError("The official news feed had no recognized entries.")
    return result


def normalize_releases(payload):
    if not isinstance(payload, list):
        raise ValueError("The releases response has an unexpected format.")
    rows = []
    seen = set()
    for entry in payload[:100]:
        if not isinstance(entry, dict) or entry.get("draft") is True:
            continue
        url = safe_https_url(entry.get("html_url"), {"github.com"})
        if not url:
            continue
        parsed = urllib.parse.urlsplit(url)
        if parsed.query or not re.fullmatch(r"/omacom/omarchy/releases/tag/[A-Za-z0-9._%+-]+", parsed.path):
            continue
        if url in seen:
            continue
        name = clean_text(entry.get("name") or entry.get("tag_name"), 240)
        if not name:
            continue
        seen.add(url)
        author = entry.get("author") if isinstance(entry.get("author"), dict) else {}
        rows.append({
            "id": "release:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:32],
            "kind": "releases",
            "name": name,
            "summary": clean_text(entry.get("body"), 600),
            "author": clean_text(author.get("login"), 120),
            "url": url,
            "timestamp": item_timestamp(entry.get("published_at")),
            "source": "Omarchy pre-release" if entry.get("prerelease") is True else "Omarchy release",
        })
    if not rows:
        raise ValueError("The releases response has no recognized releases.")
    return rows


def normalize_manual(payload):
    if not isinstance(payload, list):
        raise ValueError("The manual search index has an unexpected format.")
    rows = []
    seen = set()
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("kind") != "manual":
            continue
        slug = entry.get("slug")
        heading = entry.get("hash")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]{1,120}", slug):
            continue
        if heading is not None and (not isinstance(heading, str)
                                    or not re.fullmatch(r"[a-z0-9_-]{1,120}", heading)):
            continue
        url = MANUAL_HOME + ("" if slug == "index" else slug + "/")
        if heading:
            url += "#" + heading
        if url in seen:
            continue
        title = clean_plain_text(entry.get("title"), 160)
        section = clean_plain_text(entry.get("heading"), 160)
        text = clean_plain_text(entry.get("text"), 6000)
        if not title:
            continue
        seen.add(url)
        rows.append({
            "id": "manual:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:32],
            "kind": "manual",
            "name": title + (": " + section if section else ""),
            "summary": text[:600],
            "searchText": text,
            "author": "",
            "url": url,
            "timestamp": 0,
            "source": "Omarchy manual",
        })
        if len(rows) >= MAX_ITEMS_PER_SOURCE:
            break
    if not rows:
        raise ValueError("The manual search index has no recognized chapters.")
    return rows


class HotkeyPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article = False
        self.heading_id = ""
        self.heading_parts = None
        self.heading = ""
        self.in_table = False
        self.cells = []
        self.cell = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.in_article = True
        if not self.in_article:
            return
        if tag == "h2":
            self.heading_id = dict(attrs).get("id", "")
            self.heading_parts = []
        elif tag == "table":
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.cells = []
        elif tag == "td" and self.in_table:
            self.cell = []

    def handle_data(self, data):
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "h2" and self.heading_parts is not None:
            self.heading = clean_plain_text("".join(self.heading_parts).rstrip("# "), 100)
            self.heading_parts = None
        elif tag == "td" and self.cell is not None:
            self.cells.append(clean_plain_text("".join(self.cell), 600))
            self.cell = None
        elif tag == "tr" and self.in_table and len(self.cells) >= 2:
            self.rows.append((self.heading_id, self.heading, self.cells))
            self.cells = []
        elif tag == "table":
            self.in_table = False
        elif tag == "article":
            self.in_article = False


def normalize_hotkeys(payload):
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("The hotkeys page is not valid UTF-8.") from error
    parser = HotkeyPageParser()
    parser.feed(page)
    rows = []
    seen = set()
    for section_id, section, cells in parser.rows:
        if not re.fullmatch(r"[a-z0-9_-]{1,120}", section_id) or not cells[0] or not cells[1]:
            continue
        summary = " · ".join(cell for cell in cells[1:] if cell)
        identity = section_id + "\n" + cells[0] + "\n" + summary
        item_id = "hotkey:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        if item_id in seen:
            continue
        seen.add(item_id)
        rows.append({
            "id": item_id,
            "kind": "hotkeys",
            "name": cells[0],
            "summary": summary,
            "author": "",
            "url": HOTKEYS_HOME + "#" + section_id,
            "timestamp": 0,
            "source": section,
        })
        if len(rows) >= MAX_ITEMS_PER_SOURCE:
            break
    if not rows:
        raise ValueError("The official hotkeys page has no recognized shortcuts.")
    return rows


def youtube_search(limit, date_range):
    executable = shutil.which("yt-dlp")
    if not executable:
        raise RuntimeError("yt-dlp is not installed; install it to search YouTube.")
    params = {"search_query": "Omarchy"}
    range_code = YOUTUBE_RANGE_FILTERS[date_range]
    filters = bytes([8, range_code, 16, 1]) if range_code else b""
    search_params = bytes([8, 2]) + (bytes([18, len(filters)]) + filters if filters else b"")
    params["sp"] = base64.b64encode(search_params).decode("ascii")
    search_url = "https://www.youtube.com/results?" + urllib.parse.urlencode(params)
    command = [
        executable, "--ignore-config", "--flat-playlist",
        "--extractor-args", "youtubetab:approximate_date=1", "--skip-download",
        "--no-warnings", "--no-progress", "--socket-timeout", "15",
        "--playlist-end", str(limit), "--dump-single-json", search_url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=35, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("The YouTube search timed out.") from error
    except OSError as error:
        raise RuntimeError("Could not start yt-dlp.") from error
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise ValueError("The YouTube search response exceeded the size limit.")
    if result.returncode != 0:
        detail = clean_text(result.stderr.decode("utf-8", "replace"), 240)
        raise RuntimeError(detail or "yt-dlp could not complete the YouTube search.")
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("yt-dlp returned invalid search data.") from error
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("yt-dlp returned an unexpected search format.")
    result_items = []
    found = set()
    for row in entries:
        if not isinstance(row, dict):
            continue
        video_id = row.get("id")
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id) or video_id in found:
            continue
        title = clean_text(row.get("title"), 240)
        if not title:
            continue
        found.add(video_id)
        timestamp = row.get("timestamp")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            timestamp = 0
        result_items.append({
            "id": "video:" + video_id,
            "kind": "videos",
            "name": title,
            "summary": "",
            "author": clean_text(row.get("channel") or row.get("uploader"), 120),
            "url": "https://www.youtube.com/watch?v=" + video_id,
            "timestamp": valid_timestamp(timestamp),
            "source": "YouTube",
            "thumbnail": "https://i.ytimg.com/vi/" + video_id + "/mqdefault.jpg",
        })
        if len(result_items) >= limit:
            break
    return result_items


def fetch_source(key, settings):
    if key == "plugins":
        return normalize_plugins(fetch_json(PLUGIN_CATALOG)), ""
    if key == "themes":
        return normalize_themes(fetch_bytes(THEME_HOME)), ""
    if key == "news":
        return normalize_news(fetch_bytes(NEWS_FEED)), ""
    if key == "releases":
        return normalize_releases(fetch_json(RELEASES_API)), ""
    if key == "manual":
        return normalize_manual(fetch_json(MANUAL_INDEX)), ""
    if key == "hotkeys":
        return normalize_hotkeys(fetch_bytes(HOTKEYS_HOME)), ""
    if key == "community":
        return normalize_community(fetch_json(COMMUNITY_DATA)), ""
    if key == "events":
        return normalize_events(fetch_bytes(EVENTS_HOME)), ""
    if key == "videos":
        return youtube_search(int(settings["videosLimit"]), "all"), ""
    raise ValueError("Unknown source.")


def public_state(state, errors=None):
    read_ids = set(state["readIds"])
    saved_by_id = {item["id"]: item for item in state["savedItems"]}
    new_ids = set(state.get("newIds", []))
    output_items = {}
    unread_counts = {}
    new_counts = {}
    for key in SOURCE_KEYS:
        source = state["sources"].get(key, {})
        items = normalize_items(key, source.get("items", []))
        output_items[key] = []
        unread_counts[key] = 0
        new_counts[key] = 0
        for item in items:
            item["isRead"] = item["id"] in read_ids
            item["isNew"] = item["id"] in new_ids
            item["isSaved"] = item["id"] in saved_by_id
            if not item["isRead"]:
                unread_counts[key] += 1
            if item["isNew"]:
                new_counts[key] += 1
            output_items[key].append(item)
    saved_items = []
    for item in state["savedItems"]:
        item["isRead"] = item["id"] in read_ids
        item["isNew"] = item["id"] in new_ids
        item["isSaved"] = True
        saved_items.append(item)
    output_items["saved"] = saved_items
    return {
        "items": output_items,
        "unreadCounts": unread_counts,
        "newCounts": new_counts,
        "errors": {**{key: state["sources"].get(key, {}).get("message", "")
                      for key in SOURCE_KEYS}, **(errors or {})},
        "settings": state["settings"],
        "filters": {section: entry for section, entry in state.get("filters", {}).items()
                    if state["settings"].get("remember_" + section, True)},
        "lastFetched": {
            key: state["sources"].get(key, {}).get("fetchedAt", 0)
            for key in SOURCE_KEYS
        },
        "hasBaseline": state["baselineEstablished"],
    }


def perform_fetch(state, sources=None):
    selected = set(SOURCE_KEYS if sources is None else sources)
    if not selected <= set(SOURCE_KEYS):
        raise ValueError("Invalid refresh sources.")
    if not selected:
        return public_state(state)
    updated = {}
    errors = {}
    theme_source_changed = False
    initial_sources = {key for key in selected
                       if not state["sources"].get(key, {}).get("fetchedAt")}
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(fetch_source, key, state["settings"]): key for key in SOURCE_KEYS if key in selected}
        for future in as_completed(tasks):
            key = tasks[future]
            try:
                rows, message = future.result()
            except (RuntimeError, ValueError, OSError, urllib.error.URLError) as error:
                errors[key] = clean_text(str(error), 240) or SOURCE_ERRORS[key]
                continue
            updated[key] = (normalize_items(key, rows), message)

    for key in SOURCE_KEYS:
        if key not in selected:
            continue
        if key in updated:
            rows, message = updated[key]
            provider = ""
            if key == "themes":
                theme_source_changed = state["sources"].get(key, {}).get("provider") != "omarchy-site"
                rows = reconcile_theme_ids(rows, state)
                provider = "omarchy-site"
            state["sources"][key] = {"items": rows, "fetchedAt": int(time.time()),
                                     "message": message, "provider": provider}
        elif key not in state["sources"]:
            state["sources"][key] = {"items": [], "fetchedAt": 0, "message": errors.get(key, "")}
        else:
            message = errors.get(key, "")
            if key == "themes" and state["sources"][key].get("provider") != "omarchy-site":
                message += " Showing cached entries from the previous theme source."
                errors[key] = message
            state["sources"][key]["message"] = message

    all_ids = []
    saved_by_id = {item["id"]: item for item in state["savedItems"]}
    for key in SOURCE_KEYS:
        for item in state["sources"].get(key, {}).get("items", []):
            all_ids.append(item["id"])
            if item["id"] in saved_by_id and item.get("thumbnail"):
                saved_by_id[item["id"]]["thumbnail"] = item["thumbnail"]
    prior = set(state["knownIds"])
    if theme_source_changed:
        prior.update(item["id"] for item in state["sources"]["themes"]["items"])
    for key in initial_sources & updated.keys():
        prior.update(item["id"] for item in state["sources"][key]["items"])
    if state["baselineEstablished"]:
        unrefreshed_ids = {item["id"] for key in SOURCE_KEYS if key not in updated
                          for item in state["sources"].get(key, {}).get("items", [])}
        state["newIds"] = list(dict.fromkeys(
            [item_id for item_id in state["newIds"] if item_id in unrefreshed_ids]
            + [item_id for item_id in all_ids if item_id not in prior]))
    else:
        state["newIds"] = []
        state["baselineEstablished"] = True
    state["knownIds"] = list(dict.fromkeys(state["knownIds"] + all_ids))[-MAX_KNOWN_IDS:]
    save_state(state)
    return public_state(state, errors)


def mutate(state, command):
    if command == "clear-saved":
        if len(sys.argv) != 2:
            raise ValueError("clear-saved takes no arguments.")
        state["savedItems"] = []
    elif command == "toggle-saved":
        if len(sys.argv) != 3:
            raise ValueError("toggle-saved requires an item ID.")
        item_id = sys.argv[2]
        if not re.fullmatch(r"[a-z]+:[A-Za-z0-9._-]{1,180}", item_id):
            raise ValueError("Invalid item ID.")
        saved_by_id = {item["id"]: item for item in state["savedItems"]}
        if item_id in saved_by_id:
            del saved_by_id[item_id]
        else:
            candidate = None
            for source in state["sources"].values():
                for item in source["items"]:
                    if item["id"] == item_id:
                        candidate = item
                        break
                if candidate:
                    break
            if candidate is None:
                raise ValueError("The item is no longer available to save.")
            if len(saved_by_id) >= MAX_SAVED_ITEMS:
                raise ValueError("Saved items are full; remove one before saving another.")
            candidate["isSaved"] = True
            saved_by_id[item_id] = candidate
        state["savedItems"] = list(saved_by_id.values())
    elif command in ("toggle-read", "mark-read"):
        if len(sys.argv) != 3:
            raise ValueError(command + " requires an item ID.")
        item_id = sys.argv[2]
        if not re.fullmatch(r"[a-z]+:[A-Za-z0-9._-]{1,180}", item_id):
            raise ValueError("Invalid item ID.")
        read_ids = set(state["readIds"])
        if command == "mark-read":
            read_ids.add(item_id)
        elif item_id in read_ids:
            read_ids.remove(item_id)
        else:
            read_ids.add(item_id)
        state["readIds"] = list(read_ids)[-MAX_KNOWN_IDS:]
    elif command == "set-setting":
        if len(sys.argv) != 4:
            raise ValueError("set-setting requires a setting name and value.")
        key, value = sys.argv[2], sys.argv[3].lower()
        if key not in SETTING_VALUES or value not in SETTING_VALUES[key]:
            raise ValueError("Invalid setting.")
        state["settings"].update(valid_settings({key: value}))
        if key.startswith("remember_") and value == "false":
            state["filters"].pop(key[len("remember_"):], None)
    elif command == "save-filters":
        if len(sys.argv) != 3 or len(sys.argv[2].encode("utf-8")) > 65536:
            raise ValueError("save-filters requires bounded filter preferences.")
        filters = valid_filters(json.loads(sys.argv[2]), strict=True)
        state["filters"] = {section: entry for section, entry in filters.items()
                            if state["settings"].get("remember_" + section, True)}
    elif command == "reset-settings":
        if len(sys.argv) != 3 or sys.argv[2] not in SETTING_GROUPS:
            raise ValueError("Choose a valid settings group to restore.")
        group = sys.argv[2]
        for key in SETTING_GROUPS[group]:
            state["settings"][key] = DEFAULT_SETTINGS[key]
        if group in FILTER_SECTIONS:
            state["filters"].pop(group, None)
    else:
        raise ValueError("Unknown command.")
    save_state(state)
    print(json.dumps(public_state(state), ensure_ascii=True, separators=(",", ":")))


def system_command(command, timeout):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, errors="replace", timeout=timeout)
    except FileNotFoundError:
        return None, "Required command not found: " + command[0]
    except subprocess.TimeoutExpired:
        return None, "The command timed out: " + command[0]
    except OSError as error:
        return None, clean_text(str(error), 240)
    return result, ""


def launch_update():
    command = ["omarchy", "launch", "floating", "terminal", "with", "presentation", "omarchy-update"]
    log_path = state_path().with_name("update-launch.log")
    try:
        log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(log_path, os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w+b") as output:
            os.fchmod(output.fileno(), 0o600)
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                       start_new_session=True)
            try:
                status = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                return {"requested": True, "log": str(log_path)}
            if status != 0:
                output.seek(0)
                message = clean_plain_text(output.read(4096).decode("utf-8", errors="replace"), 240)
                raise RuntimeError(message or "Could not open the update terminal.")
    except OSError as error:
        raise RuntimeError("Could not open the update terminal: " + str(error)) from error
    return {"requested": True, "log": str(log_path)}


def theme_preview(name):
    slug = name.lower().replace(" ", "-")
    if not slug or slug.startswith(".") or any(char in slug for char in "/\\"):
        return ""
    roots = (Path.home() / ".config" / "omarchy" / "themes",
             Path(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy") / "themes")
    extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
    for root in roots:
        theme = root / slug
        try:
            if not theme.is_dir():
                continue
            resolved_theme = theme.resolve(strict=True)
            def candidates():
                for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
                    yield theme / ("preview" + suffix)
                backgrounds = theme / "backgrounds"
                if backgrounds.is_dir():
                    yield from sorted(
                        (path for path in backgrounds.iterdir() if path.suffix.lower() in extensions),
                        key=lambda path: path.name)

            for candidate in candidates():
                try:
                    image = candidate.resolve(strict=True)
                    if (image.is_relative_to(resolved_theme) and image.is_file()
                            and image.stat().st_size <= 16 * 1024 * 1024):
                        return image.as_uri()
                except (OSError, RuntimeError):
                    continue
        except (OSError, RuntimeError):
            continue
    return ""


def theme_status():
    current, error = system_command(["omarchy", "theme", "current"], 10)
    if current is None:
        current_field = {"value": "", "error": error}
    elif current.returncode != 0 or not current.stdout.strip():
        current_field = {"value": "", "error": clean_plain_text(current.stderr, 240) or
                         "Could not read the current theme."}
    else:
        current_field = {"value": clean_plain_text(current.stdout, 240), "error": ""}

    result, error = system_command(["omarchy", "theme", "list"], 15)
    themes = []
    list_error = ""
    if result is None:
        list_error = error
    elif result.returncode != 0:
        list_error = clean_plain_text(result.stderr or result.stdout, 240) or "Could not list installed themes."
    else:
        names = result.stdout.splitlines()
        for name in names[:MAX_ITEMS_PER_SOURCE]:
            if (not name or name[0] in ".- " or len(name) > 160
                    or any(not char.isprintable() or char in "/\\<>" for char in name)):
                list_error = "Some installed theme names could not be displayed safely."
                continue
            if name not in themes:
                themes.append(name)
        if len(names) > MAX_ITEMS_PER_SOURCE:
            list_error = "The installed theme list exceeded the display limit."
        elif not themes and not list_error:
            list_error = clean_plain_text(result.stderr, 240) or "No installed themes were found."
        elif result.stderr.strip() and not list_error:
            list_error = clean_plain_text(result.stderr, 240)
    previews = {name: preview for name in themes if (preview := theme_preview(name))}
    return {"current": current_field, "themes": themes, "previews": previews, "listError": list_error,
            "actionError": "", "warning": ""}


def set_theme(name):
    state = theme_status()
    if state["listError"]:
        raise RuntimeError(state["listError"])
    if name not in state["themes"]:
        raise ValueError("The selected theme is no longer available.")
    if state["current"]["error"]:
        raise RuntimeError(state["current"]["error"])
    if name == state["current"]["value"]:
        return state
    result, error = system_command(["omarchy", "theme", "set", name], 180)
    updated = theme_status()
    if result is None:
        updated["actionError"] = error + " Check the current theme."
    elif result.returncode != 0:
        updated["actionError"] = clean_plain_text(result.stderr or result.stdout, 240) or "Could not apply the theme."
    elif updated["current"]["error"]:
        updated["actionError"] = "The theme change completed, but the current theme could not be confirmed."
    elif updated["current"]["value"] != name:
        updated["actionError"] = "The selected theme is not the current theme."
    elif result.stderr.strip():
        updated["warning"] = clean_plain_text(result.stderr, 240)
    return updated


def system_status():
    fields = {}
    for key, command in (("version", ["omarchy", "version"]), ("theme", ["omarchy", "theme", "current"])):
        result, error = system_command(command, 10)
        if result is None:
            fields[key] = {"value": "", "error": error}
        elif result.returncode != 0 or not result.stdout.strip():
            fields[key] = {"value": "", "error": clean_text(result.stderr, 200) or
                           "Could not read " + key + "."}
        else:
            fields[key] = {"value": clean_plain_text(result.stdout, 240), "error": ""}
    result, error = system_command(["checkupdates", "--nocolor"], 60)
    if result is None:
        fields["update"] = {"status": "unknown", "detail": error}
    elif result.returncode not in (0, 2):
        fields["update"] = {"status": "unknown", "detail": clean_text(result.stderr, 240) or
                            "The package update check failed."}
    else:
        database = os.environ.get("CHECKUPDATES_DB") or os.path.join(
            os.environ.get("TMPDIR") or "/tmp", "checkup-db-" + str(os.getuid()))
        query, error = system_command(["pacman", "-Qu", "--dbpath", database, "--color", "never"], 15)
        if query is None:
            fields["update"] = {"status": "unknown", "detail": error}
        elif query.returncode != 0:
            fields["update"] = {"status": "unknown", "detail": clean_text(query.stderr, 240) or
                                "The package database query failed."}
        else:
            update = next((line for line in query.stdout.splitlines()
                           if re.match(r"^omarchy(?:-dev)?\s", line) and not re.search(r"\[.*\]", line)), "")
            fields["update"] = {"status": "available" if update else "none",
                                "detail": clean_plain_text(update, 240)}
    fields["development"] = os.environ.get("OMARCHY_PATH", "/usr/share/omarchy").rstrip("/") != "/usr/share/omarchy"
    return fields


def main():
    if len(sys.argv) < 2:
        raise ValueError("Choose load, fetch, mark-read, toggle-read, toggle-saved, or set-setting.")
    if sys.argv[1] == "display-load":
        if len(sys.argv) != 2:
            raise ValueError("display-load takes no arguments.")
        print(json.dumps(load_display(), separators=(",", ":")))
        return
    if sys.argv[1] == "system-status":
        if len(sys.argv) != 2:
            raise ValueError("system-status takes no arguments.")
        print(json.dumps(system_status(), ensure_ascii=True, separators=(",", ":")))
        return
    if sys.argv[1] == "launch-update":
        if len(sys.argv) != 2:
            raise ValueError("launch-update takes no arguments.")
        print(json.dumps(launch_update(), separators=(",", ":")))
        return
    if sys.argv[1] == "theme-status":
        if len(sys.argv) != 2:
            raise ValueError("theme-status takes no arguments.")
        print(json.dumps(theme_status(), ensure_ascii=True, separators=(",", ":")))
        return
    if sys.argv[1] == "theme-set":
        if len(sys.argv) != 3:
            raise ValueError("theme-set requires an installed theme name.")
        print(json.dumps(set_theme(sys.argv[2]), ensure_ascii=True, separators=(",", ":")))
        return
    if sys.argv[1] == "display-save":
        if len(sys.argv) != 5 or not all(re.fullmatch(r"[0-9]{1,5}", x) for x in sys.argv[3:]):
            raise ValueError("display-save requires a mode, width, and height.")
        display = {"mode": sys.argv[2], "width": int(sys.argv[3]), "height": int(sys.argv[4])}
        print(json.dumps(save_display(display), separators=(",", ":")))
        return
    state = load_state()
    if sys.argv[1] == "load":
        print(json.dumps(public_state(state), ensure_ascii=True, separators=(",", ":")))
    elif sys.argv[1] == "fetch":
        if len(sys.argv) > 3 or (len(sys.argv) == 3 and sys.argv[2] != "on-open"):
            raise ValueError("fetch accepts only the optional on-open mode.")
        sources = [key for key in SOURCE_KEYS if state["settings"].get("refresh_" + key, True)] \
            if len(sys.argv) == 3 and state["settings"]["refreshOnOpen"] else (
                [] if len(sys.argv) == 3 else SOURCE_KEYS)
        payload = perform_fetch(state, sources)
        result = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if len(result.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("The combined data response exceeded the output limit.")
        print(result)
    elif sys.argv[1] in ("mark-read", "toggle-read", "toggle-saved", "set-setting",
                        "save-filters", "reset-settings", "clear-saved"):
        mutate(state, sys.argv[1])
    else:
        raise ValueError("Unknown command.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, urllib.error.URLError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": clean_text(str(error), 240) or "The request failed."}), file=sys.stderr)
        sys.exit(1)
