#!/usr/bin/env python3

import hashlib
import base64
import fcntl
import html
import json
import locale
import os
import re
import selectors
import signal
import shutil
import stat
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
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
OPTIONAL_SECTIONS = SOURCE_KEYS + ("system",)
FILTER_SECTIONS = SOURCE_KEYS + ("saved",)
DASHBOARD_PANELS = ("system", "catchUp", "events", "saved")
DEFAULT_SETTINGS.update({
    "showPreviews": True, "density": "comfortable", "markReadOnOpen": True,
    "markReadOnScroll": True, "navigationWidth": 160,
    "systemCheckOnOpen": True, "periodicRefresh": True, "refreshInterval": 30,
    "newItemNotifications": True,
    "periodicVideos": False,
    **{"section_" + section: True for section in OPTIONAL_SECTIONS},
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
    "navigationWidth": {str(width) for width in range(160, 221)},
    "refreshInterval": {"10", "15", "20", "30", "45", "60"},
    "dashboardOrder": {",".join(order).lower() for order in permutations(DASHBOARD_PANELS)},
    "catchUpLimit": {"4", "8", "12", "16"},
    "eventsLimit": {"1", "3", "5"},
    "savedLimit": {"2", "4", "8"},
})
# Settings values are normalized to lowercase on disk and at the CLI boundary.
DEFAULT_SETTINGS["dashboardOrder"] = DEFAULT_SETTINGS["dashboardOrder"].lower()
SETTING_GROUPS = {
    "general": {"showPreviews", "density", "markReadOnOpen", "markReadOnScroll", "navigationWidth"},
    "sections": {"section_" + section for section in OPTIONAL_SECTIONS},
    "dashboard": {key for key in DEFAULT_SETTINGS if key.startswith("dashboard")
                  or key in ("catchUpLimit", "eventsLimit", "savedLimit")},
    "refresh": {"refreshOnOpen", "systemCheckOnOpen", "periodicRefresh", "refreshInterval",
                "newItemNotifications",
                "periodicVideos"} |
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


def bounded_json(value):
    result = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if len(result) + 1 > MAX_OUTPUT_BYTES:
        raise ValueError("The combined data response exceeded the output limit.")
    return result


def emit_json(value):
    print(bounded_json(value))


MAX_STATE_BYTES = 16 * 1024 * 1024
STATE_LOCK_NAME = ".state.lock"
STATE_LOCK_TIMEOUT = 5
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
MAX_LOCAL_PREVIEW_BYTES = 16 * 1024 * 1024
THUMBNAIL_TIMEOUT = 15
MAX_THUMBNAIL_DIMENSION = 4096
MAX_THUMBNAIL_PIXELS = 8 * 1024 * 1024
MAX_CACHE_FILES = 64
MAX_CACHE_BYTES = 32 * 1024 * 1024


def state_base_dir():
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        base = Path(state_home)
    else:
        base = Path.home() / ".local" / "state"
    return base.absolute() / "all-things-omarchy"


def state_path():
    return state_base_dir() / "state.json"


def state_lock_path():
    return state_path().with_name(STATE_LOCK_NAME)


@contextmanager
def private_directory(path):
    """Pin each directory component without following symlinks."""
    path = Path(path).absolute()
    owner = os.getuid()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            ancestor = os.fstat(descriptor)
            if ancestor.st_uid not in (0, owner):
                raise RuntimeError("The local plugin state directory has the wrong owner.")
            if (ancestor.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                    and not (ancestor.st_uid == 0 and ancestor.st_mode & stat.S_ISVTX)):
                raise RuntimeError("The local plugin state directory has an unsafe writable ancestor.")
            if component in (".", ".."):
                raise RuntimeError("The local plugin state directory is unsafe.")
            try:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if info.st_uid != owner:
            raise RuntimeError("The local plugin state directory has the wrong owner.")
        os.fchmod(descriptor, 0o700)
        yield descriptor
    finally:
        os.close(descriptor)


def private_file(directory, name, flags, create=False):
    try:
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise
    else:
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise RuntimeError("The local plugin state file is not a private regular file.")
    descriptor = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK
                         | (os.O_CREAT if create else 0), 0o600, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise RuntimeError("The local plugin state file is not a private regular file.")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def bounded_file_read(path, limit):
    with private_directory(path.parent) as directory:
        descriptor = private_file(directory, path.name, os.O_RDONLY)
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("The local plugin state file is too large.")
    return raw


@contextmanager
def advisory_lock(path, timeout=STATE_LOCK_TIMEOUT):
    deadline = time.monotonic() + timeout
    with private_directory(path.parent) as directory:
        descriptor = private_file(directory, path.name, os.O_RDWR, create=True)
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("Timed out waiting for the local plugin state lock.")
                    time.sleep(min(0.05, remaining))
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


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
        raw = bounded_file_read(path, MAX_STATE_BYTES)
    except FileNotFoundError:
        return empty_state()
    except ValueError as error:
        raise RuntimeError("The local plugin state file is too large.") from error
    except OSError as error:
        raise RuntimeError("Could not read the local plugin state.") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
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
    raw = json.dumps(state, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("The local plugin state file is too large.")
    atomic_private_write(path, raw)


def atomic_private_write(path, raw):
    try:
        with private_directory(path.parent) as directory:
            try:
                existing = private_file(directory, path.name, os.O_RDONLY)
            except FileNotFoundError:
                pass
            else:
                os.close(existing)
            temporary = ".state-" + os.urandom(16).hex()
            descriptor = private_file(directory, temporary, os.O_WRONLY | os.O_EXCL, create=True)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
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
        raw = bounded_file_read(path, 4096)
    except FileNotFoundError:
        return dict(DEFAULT_DISPLAY)
    except ValueError as error:
        raise ValueError("The saved display preference is too large.") from error
    except OSError as error:
        raise RuntimeError("Could not read the saved display preference.") from error
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
        elif key.endswith("Limit") or key in ("refreshInterval", "navigationWidth"):
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


def valid_thumbnail(value):
    if (not isinstance(value, str) or not value.startswith("https://")
            or any(ord(char) < 33 for char in value)):
        return ""
    return value if any(safe_thumbnail(kind, value) == value
                        for kind in ("plugins", "themes", "videos", "news", "events")) else ""


class ThumbnailRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        target = valid_thumbnail(new_url)
        if (not target or urllib.parse.urlsplit(target).hostname
                != urllib.parse.urlsplit(request.full_url).hostname):
            raise ValueError("The thumbnail redirected outside its allowlist.")
        return super().redirect_request(request, response, code, message, headers, target)


def download_thumbnail_bytes(url):
    if not valid_thumbnail(url):
        raise ValueError("The thumbnail URL is not allowed.")
    deadline = time.monotonic() + THUMBNAIL_TIMEOUT
    opener = urllib.request.build_opener(ThumbnailRedirectHandler())
    request = urllib.request.Request(url, headers={"User-Agent": "AllThingsOmarchy/0.1"})
    with opener.open(request, timeout=THUMBNAIL_TIMEOUT) as response:
        if (not valid_thumbnail(response.geturl()) or urllib.parse.urlsplit(response.geturl()).hostname
                != urllib.parse.urlsplit(url).hostname):
            raise ValueError("The thumbnail redirected outside its allowlist.")
        length = response.headers.get("Content-Length")
        if length is not None and (int(length) < 0 or int(length) > MAX_THUMBNAIL_BYTES):
            raise ValueError("The thumbnail exceeded the size limit.")
        body = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError("The thumbnail download timed out.")
            chunk = response.read1(min(65536, MAX_THUMBNAIL_BYTES + 1 - len(body)))
            if not chunk:
                return bytes(body)
            body.extend(chunk)
            if len(body) > MAX_THUMBNAIL_BYTES:
                raise ValueError("The thumbnail exceeded the size limit.")


def thumbnail_dimensions(body):
    """Inspect encoded dimensions without allocating a decoded pixel buffer."""
    dimensions = []
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        if len(body) < 33 or body[12:16] != b"IHDR" or body[8:12] != b"\0\0\0\r":
            raise ValueError("The thumbnail PNG header is invalid.")
        dimensions.append(struct.unpack(">II", body[16:24]))
        while offset + 12 <= len(body):
            length = int.from_bytes(body[offset:offset + 4], "big")
            kind = body[offset + 4:offset + 8]
            if offset + 12 + length > len(body) or kind == b"acTL":
                raise ValueError("The thumbnail PNG is truncated or animated.")
            if kind == b"IHDR" and offset != 8:
                raise ValueError("The thumbnail PNG has multiple image headers.")
            offset += 12 + length
            if kind == b"IEND":
                break
        else:
            raise ValueError("The thumbnail PNG is incomplete.")
    elif body.startswith(b"\xff\xd8"):
        offset = 2
        while offset < len(body):
            if body[offset] != 255:
                raise ValueError("The thumbnail JPEG header is invalid.")
            while offset < len(body) and body[offset] == 255:
                offset += 1
            if offset >= len(body):
                break
            marker = body[offset]
            offset += 1
            if marker in (0xDA, 0xD9):
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(body[offset:offset + 2], "big")
            if length < 2 or offset + length > len(body):
                raise ValueError("The thumbnail JPEG is truncated.")
            if marker in (0xC0, 0xC1, 0xC2):
                if length < 8:
                    raise ValueError("The thumbnail JPEG frame is invalid.")
                height, width = struct.unpack(">HH", body[offset + 3:offset + 7])
                dimensions.append((width, height))
            elif marker in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                raise ValueError("The thumbnail JPEG frame format is unsupported.")
            offset += length
        if len(dimensions) != 1:
            raise ValueError("The thumbnail JPEG image header is missing or ambiguous.")
    elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        if len(body) < 20 or int.from_bytes(body[4:8], "little") + 8 != len(body):
            raise ValueError("The thumbnail WebP container is invalid.")
        offset = 12
        frame_count = 0
        while offset + 8 <= len(body):
            kind = body[offset:offset + 4]
            length = int.from_bytes(body[offset + 4:offset + 8], "little")
            data = body[offset + 8:offset + 8 + length]
            if len(data) != length or kind in (b"ANIM", b"ANMF"):
                raise ValueError("The thumbnail WebP is truncated or animated.")
            if kind == b"VP8X":
                if length != 10 or data[0] & 2:
                    raise ValueError("The thumbnail WebP extended header is invalid or animated.")
                dimensions.append((int.from_bytes(data[4:7], "little") + 1,
                                   int.from_bytes(data[7:10], "little") + 1))
            elif kind == b"VP8 ":
                if length < 10 or data[0] & 1 or data[3:6] != b"\x9d\x01\x2a":
                    raise ValueError("The thumbnail WebP frame is invalid.")
                width, height = struct.unpack("<HH", data[6:10])
                dimensions.append((width & 0x3fff, height & 0x3fff))
                frame_count += 1
            elif kind == b"VP8L":
                if length < 5 or data[0] != 0x2f:
                    raise ValueError("The thumbnail WebP lossless header is invalid.")
                bits = int.from_bytes(data[1:5], "little")
                dimensions.append(((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1))
                frame_count += 1
            offset += 8 + length + (length & 1)
        if frame_count != 1 or offset != len(body):
            raise ValueError("The thumbnail WebP image header is missing or ambiguous.")
    else:
        raise ValueError("The thumbnail image format is unsupported.")
    for width, height in dimensions:
        if (not (0 < width <= MAX_THUMBNAIL_DIMENSION and 0 < height <= MAX_THUMBNAIL_DIMENSION)
                or width * height > MAX_THUMBNAIL_PIXELS):
            raise ValueError("The thumbnail image dimensions exceeded the limit.")
    if not dimensions or any(value != dimensions[0] for value in dimensions):
        raise ValueError("The thumbnail image dimensions are inconsistent.")
    return dimensions[0]


def prune_thumbnail_cache(cache, incoming=0, reserve=0, keep=""):
    with private_directory(cache) as directory:
        entries = []
        for name in os.listdir(directory):
            if not re.fullmatch(r"[0-9a-f]{64}\.img", name):
                if name != ".cache.lock":
                    raise RuntimeError("The thumbnail cache contains an unexpected file.")
                continue
            descriptor = private_file(directory, name, os.O_RDONLY)
            try:
                info = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            entries.append((info.st_mtime_ns, name, info.st_size))
        total = sum(entry[2] for entry in entries)
        count = len(entries)
        for _, name, size in sorted(entries):
            if count + reserve <= MAX_CACHE_FILES and total + incoming <= MAX_CACHE_BYTES:
                break
            if name != keep:
                os.unlink(name, dir_fd=directory)
                total -= size
                count -= 1
        if count + reserve > MAX_CACHE_FILES or total + incoming > MAX_CACHE_BYTES:
            raise ValueError("The thumbnail exceeds the cache limit.")


def thumbnail(url):
    if not valid_thumbnail(url):
        raise ValueError("The thumbnail URL is not allowed.")
    base = state_path().parent
    with private_directory(base):
        pass
    cache = base / "thumbnails"
    path = cache / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".img")
    with advisory_lock(cache / ".cache.lock"):
        try:
            body = bounded_file_read(path, MAX_THUMBNAIL_BYTES)
        except FileNotFoundError:
            try:
                result = bounded_run([sys.executable, str(Path(__file__).absolute()),
                                      "_thumbnail-download", url],
                                     THUMBNAIL_TIMEOUT, MAX_THUMBNAIL_BYTES + 4096)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("The thumbnail download timed out.") from error
            if result.returncode:
                try:
                    detail = json.loads(result.stderr).get("error", "")
                except (ValueError, AttributeError):
                    detail = result.stderr.decode("utf-8", "replace")
                raise RuntimeError(clean_plain_text(detail, 240) or "The thumbnail download failed.")
            body = result.stdout
            if len(body) > MAX_THUMBNAIL_BYTES:
                raise ValueError("The thumbnail exceeded the size limit.")
            thumbnail_dimensions(body)
            if len(body) > MAX_CACHE_BYTES or MAX_CACHE_FILES < 1:
                raise ValueError("The thumbnail exceeds the cache limit.")
            prune_thumbnail_cache(cache, incoming=len(body), reserve=1)
            atomic_private_write(path, body)
        else:
            thumbnail_dimensions(body)
            prune_thumbnail_cache(cache, keep=path.name)
    return {"url": path.absolute().as_uri()}


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


class OutputLimitError(ValueError):
    pass


_active_process_groups = set()
_request_interrupted = False
_spawning_on_main = False


def interrupt_request(signum, frame):
    global _request_interrupted
    if _request_interrupted:
        return
    _request_interrupted = True
    # Thread-pool workers own detached process groups too. Signal them immediately;
    # their bounded_run finally blocks perform the wait/reap, without handler locks.
    for pid in tuple(_active_process_groups):
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    # Let Popen finish assigning/registering a child before raising into its
    # caller, so a signal in the spawn window cannot orphan that child.
    if not _spawning_on_main:
        raise RuntimeError("The backend request was interrupted.")


def bounded_run(command, timeout, max_bytes, *, text=False, errors=None):
    """Drain both pipes concurrently, bounding memory and the entire process tree."""
    global _spawning_on_main
    if _request_interrupted:
        raise RuntimeError("The backend request was interrupted.")
    deadline = time.monotonic() + timeout
    output, diagnostic = bytearray(), bytearray()
    failed = True
    process = None
    try:
        on_main = threading.current_thread() is threading.main_thread()
        if on_main:
            _spawning_on_main = True
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            _active_process_groups.add(process.pid)
        finally:
            if on_main:
                _spawning_on_main = False
        if _request_interrupted:
            raise RuntimeError("The backend request was interrupted.")
        with selectors.DefaultSelector() as selector:
            for pipe, buffer in ((process.stdout, output), (process.stderr, diagnostic)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, buffer)
            while selector.get_map() or process.poll() is None:
                if _request_interrupted:
                    raise RuntimeError("The backend request was interrupted.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout, bytes(output), bytes(diagnostic))
                events = selector.select(min(remaining, 0.05))
                for key, _ in events:
                    budget = max_bytes - len(output) - len(diagnostic)
                    chunk = os.read(key.fd, min(65536, budget + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if len(chunk) > budget:
                        raise OutputLimitError("The command output exceeded the size limit.")
                    key.data.extend(chunk)
            status = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        failed = False
    finally:
        if failed and process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            # A reaped parent may still have descendants keeping its pipes open.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if process is not None:
            _active_process_groups.discard(process.pid)
            process.stdout.close()
            process.stderr.close()
    if text:
        encoding = "utf-8" if sys.flags.utf8_mode else locale.getencoding()
        stdout = bytes(output).decode(encoding, errors or "strict").replace("\r\n", "\n").replace("\r", "\n")
        stderr = bytes(diagnostic).decode(encoding, errors or "strict").replace("\r\n", "\n").replace("\r", "\n")
    else:
        stdout, stderr = bytes(output), bytes(diagnostic)
    return subprocess.CompletedProcess(command, status, stdout, stderr)


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
        result = bounded_run(command, timeout=35, max_bytes=MAX_RESPONSE_BYTES)
    except OutputLimitError as error:
        raise ValueError("The YouTube search response exceeded the size limit.") from error
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


def plugin_version():
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version.strip() or len(version) > 64:
        raise ValueError("The plugin manifest does not contain a valid version.")
    return version


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
            item["isNew"] = item["id"] in new_ids and item["id"] not in read_ids
            item["isSaved"] = item["id"] in saved_by_id
            if not item["isRead"]:
                unread_counts[key] += 1
            if item["isNew"]:
                new_counts[key] += 1
            output_items[key].append(item)
    saved_items = []
    for item in state["savedItems"]:
        item["isRead"] = item["id"] in read_ids
        item["isNew"] = item["id"] in new_ids and item["id"] not in read_ids
        item["isSaved"] = True
        saved_items.append(item)
    output_items["saved"] = saved_items
    return {
        "pluginVersion": plugin_version(),
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
    selected = {key for key in selected if state["settings"].get("section_" + key, True)}
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
        unrefreshed_ids.update(item["id"] for item in state["savedItems"])
        pending_new_ids = set(state["newIds"]) - set(state["readIds"])
        state["newIds"] = list(dict.fromkeys(
            [item_id for item_id in all_ids if item_id not in prior or item_id in pending_new_ids]
            + [item_id for item_id in pending_new_ids if item_id in unrefreshed_ids]))
    else:
        state["newIds"] = []
        state["baselineEstablished"] = True
    state["knownIds"] = list(dict.fromkeys(state["knownIds"] + all_ids))[-MAX_KNOWN_IDS:]
    save_state(state)
    return public_state(state, errors)


def mutate(state, command):
    if command in ("mark-all-read", "mark-all-unread", "mark-read-items"):
        if len(sys.argv) != 3:
            raise ValueError(command + " requires a section or item list.")
        if command == "mark-read-items":
            raw = sys.argv[2]
            if len(raw.encode("utf-8")) > 65536:
                raise ValueError("The item list is too large.")
            item_ids = json.loads(raw)
            if not isinstance(item_ids, list) or not 1 <= len(item_ids) <= 200 or any(
                    not isinstance(item_id, str)
                    or not re.fullmatch(r"[a-z]+:[A-Za-z0-9._-]{1,180}", item_id)
                    for item_id in item_ids):
                raise ValueError("Invalid item list.")
            available_ids = {item["id"] for source in state["sources"].values()
                             for item in source["items"]}
            available_ids.update(item["id"] for item in state["savedItems"])
            if not set(item_ids) <= available_ids:
                raise ValueError("An item is no longer available to mark read.")
        else:
            section = sys.argv[2]
            if section not in FILTER_SECTIONS + ("dashboard",):
                raise ValueError("Choose a valid item section.")
            if section == "dashboard":
                items = [item for key, source in state["sources"].items()
                         if state["settings"].get("section_" + key, True)
                         for item in source["items"]]
                items += state["savedItems"]
            else:
                items = state["savedItems"] if section == "saved" else state["sources"].get(
                    section, {}).get("items", [])
            item_ids = [item["id"] for item in items]
        selected_ids = set(item_ids)
        read_ids = set(state["readIds"])
        if command == "mark-all-unread":
            read_ids.difference_update(selected_ids)
        else:
            read_ids.update(selected_ids)
        if len(read_ids) > MAX_KNOWN_IDS:
            raise ValueError("Read history is full; mark some items unread first.")
        state["readIds"] = sorted(read_ids)
        if command != "mark-all-unread":
            state["newIds"] = [item_id for item_id in state["newIds"]
                               if item_id not in selected_ids]
    elif command == "clear-saved":
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
        if item_id in read_ids:
            state["newIds"] = [known_id for known_id in state["newIds"] if known_id != item_id]
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
    result = bounded_json(public_state(state))
    save_state(state)
    print(result)


def system_command(command, timeout):
    try:
        result = bounded_run(command, timeout, MAX_OUTPUT_BYTES, text=True, errors="replace")
    except FileNotFoundError:
        return None, "Required command not found: " + command[0]
    except subprocess.TimeoutExpired:
        return None, "The command timed out: " + command[0]
    except OutputLimitError:
        return None, "The command output exceeded the size limit: " + command[0]
    except OSError as error:
        return None, clean_text(str(error), 240)
    return result, ""


def launch_update():
    command = ["omarchy", "launch", "floating", "terminal", "with", "presentation", "omarchy-update"]
    log_path = state_path().with_name("update-launch.log")
    try:
        with advisory_lock(state_lock_path()), private_directory(log_path.parent) as directory:
            descriptor = private_file(directory, log_path.name, os.O_RDWR, create=True)
            with os.fdopen(descriptor, "w+b") as output:
                output.truncate(0)
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


def theme_preview(name, errors=None):
    slug = name.lower().replace(" ", "-")
    if not slug or slug.startswith(".") or any(char in slug for char in "/\\"):
        return ""
    roots = (Path.home() / ".config" / "omarchy" / "themes",
             Path(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy") / "themes")
    extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def report(error):
        if errors is not None and len(errors) < 20:
            errors.append(clean_plain_text(name + ": " + str(error), 240))

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
                    images = []
                    for index, path in enumerate(backgrounds.iterdir()):
                        if index >= 256:
                            report("The theme background file limit was exceeded.")
                            break
                        if path.suffix.lower() in extensions:
                            images.append(path)
                    yield from sorted(images, key=lambda path: path.name)

            for candidate in candidates():
                try:
                    image = candidate.resolve(strict=True)
                    if not image.is_relative_to(resolved_theme):
                        report("A theme preview points outside its theme directory.")
                        continue
                    info = image.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError("The theme preview is not a regular file.")
                    descriptor = os.open(image, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(descriptor, "rb") as source:
                        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                            raise ValueError("The theme preview is not a regular file.")
                        body = source.read(MAX_LOCAL_PREVIEW_BYTES + 1)
                    if len(body) > MAX_LOCAL_PREVIEW_BYTES:
                        raise ValueError("The theme preview exceeded the size limit.")
                    thumbnail_dimensions(body)
                    return image.as_uri()
                except FileNotFoundError:
                    continue
                except (OSError, RuntimeError, ValueError) as error:
                    report(error)
        except (OSError, RuntimeError) as error:
            report(error)
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
    previews = {}
    preview_errors = []
    for name in themes:
        if preview := theme_preview(name, preview_errors):
            previews[name] = preview
    warning = clean_plain_text("Some theme previews were rejected: " + "; ".join(preview_errors), 240) \
        if preview_errors else ""
    return {"current": current_field, "themes": themes, "previews": previews, "listError": list_error,
            "actionError": "", "warning": warning}


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
        updated["warning"] = clean_plain_text(
            "; ".join(value for value in (updated["warning"], result.stderr) if value), 240)
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
    if sys.argv[1] in ("thumbnail", "_thumbnail-download"):
        if len(sys.argv) != 3:
            raise ValueError("thumbnail requires one allowed HTTPS URL.")
        if sys.argv[1] == "_thumbnail-download":
            sys.stdout.buffer.write(download_thumbnail_bytes(sys.argv[2]))
        else:
            emit_json(thumbnail(sys.argv[2]))
        return
    if sys.argv[1] == "display-load":
        if len(sys.argv) != 2:
            raise ValueError("display-load takes no arguments.")
        emit_json(load_display())
        return
    if sys.argv[1] == "system-status":
        if len(sys.argv) != 2:
            raise ValueError("system-status takes no arguments.")
        emit_json(system_status())
        return
    if sys.argv[1] == "launch-update":
        if len(sys.argv) != 2:
            raise ValueError("launch-update takes no arguments.")
        emit_json(launch_update())
        return
    if sys.argv[1] == "theme-status":
        if len(sys.argv) != 2:
            raise ValueError("theme-status takes no arguments.")
        emit_json(theme_status())
        return
    if sys.argv[1] == "theme-set":
        if len(sys.argv) != 3:
            raise ValueError("theme-set requires an installed theme name.")
        emit_json(set_theme(sys.argv[2]))
        return
    if sys.argv[1] == "display-save":
        if len(sys.argv) != 5 or not all(re.fullmatch(r"[0-9]{1,5}", x) for x in sys.argv[3:]):
            raise ValueError("display-save requires a mode, width, and height.")
        display = {"mode": sys.argv[2], "width": int(sys.argv[3]), "height": int(sys.argv[4])}
        with advisory_lock(state_lock_path()):
            emit_json(save_display(display))
        return
    with advisory_lock(state_lock_path()):
        state_main()


def state_main():
    state = load_state()
    if sys.argv[1] == "load":
        emit_json(public_state(state))
    elif sys.argv[1] == "fetch":
        if len(sys.argv) > 3 or (len(sys.argv) == 3 and sys.argv[2] not in ("on-open", "scheduled")):
            raise ValueError("fetch accepts only on-open or scheduled mode.")
        mode = sys.argv[2] if len(sys.argv) == 3 else "manual"
        selected = state["settings"]
        enabled_sources = [key for key in SOURCE_KEYS
                           if selected.get("section_" + key, True)]
        if mode == "on-open":
            sources = [key for key in enabled_sources if selected.get("refresh_" + key, True)] \
                if selected["refreshOnOpen"] else []
        elif mode == "scheduled":
            sources = [key for key in enabled_sources if selected.get("refresh_" + key, True)
                       and (key != "videos" or selected.get("periodicVideos", False))] \
                if selected.get("periodicRefresh", True) else []
        else:
            sources = enabled_sources
        payload = perform_fetch(state, sources)
        emit_json(payload)
    elif sys.argv[1] in ("mark-read", "toggle-read", "toggle-saved", "set-setting",
                        "mark-all-read", "mark-all-unread", "mark-read-items",
                        "save-filters", "reset-settings", "clear-saved"):
        mutate(state, sys.argv[1])
    else:
        raise ValueError("Unknown command.")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt_request)
    signal.signal(signal.SIGINT, interrupt_request)
    try:
        main()
    except (ValueError, RuntimeError, OSError, urllib.error.URLError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": clean_text(str(error), 240) or "The request failed."}), file=sys.stderr)
        sys.exit(1)
