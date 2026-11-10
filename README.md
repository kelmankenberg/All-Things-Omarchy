# All Things Omarchy

[Changelog](CHANGELOG.md)

One place to browse the Omarchy plugin marketplace, official community themes,
YouTube search results, official Omarchy News, releases, the manual, default
hotkeys, community resources, meetups, and local system information. It opens as a panel attached
to its bar button by default, with toolbar options for a separate window and a
full-screen window. The last display mode and window size are remembered when
reopening; the window manager may override the size when the window is tiled.
The toolbar's navigation toggle switches between labeled and icon-only navigation;
hover an icon for its label.
Drag the navigation's right-edge divider to adjust its expanded width from
160 to 220 pixels (scaled with the interface). The width is saved between
sessions; collapsed navigation stays at 52 pixels.

## Sections

- **Dashboard** is an actionable briefing: Omarchy package update status and
  update/check controls, source errors with a retry-all button, eight new/unread
  items across feeds, the next three meetups, and four saved unread items.
  Items offer Open, Save/Unsave, and Mark Read actions; source refresh times
  show when cached content was last successfully fetched. NEW means newly
  discovered by a feed refresh, not necessarily published since your last
  visit. New badges remain until marked read; the bar icon changes color while
  any new items are unacknowledged.
- **Plugins**, **Themes**, **YouTube**, and **News** each have their own text
  filter and read/unread and save actions. Plugins, YouTube, and News also have
  date selectors (today, this week, this month, or all time). This week starts
  on Monday; dates use the local calendar. **Releases** has the same date
  selector and shows GitHub release publication dates, including pre-releases.
  Each selector is remembered while
  the shell is running. Themes follow the official site's order; the site does
  not provide listing dates.
- Type in a section's filter to narrow results, then press Enter or the plus
  button to add the text as a term. Results must match every term; remove a
  term with its × button or press Backspace at the start of the filter text.
  Phrases are supported, and each section retains its own terms and unfinished
  input while the shell is running.
- **Manual** searches the official manual's chapter and section text and opens
  matching sections. **Hotkeys** searches the official documented default
  shortcuts; locally customized bindings may differ. Both preserve source
  order and have no date controls.
- **Community** lists the Omarchy Hub's community-submitted applications,
  tools, guides, and discussions, in the Hub's order. It has no date controls
  because the catalog does not provide publication dates.
- **Events** lists official Omarchy meetups, with upcoming events first and
  previously started events afterward. Dates and times use your local time zone;
  date filters cover the whole local calendar period, including future events.
- **My System** shows the installed Omarchy version, current theme, and Omarchy
  package update status. Its theme dropdown shows local theme previews (or a
  fallback icon) and applies an installed theme using `omarchy theme set`.
  Unless automatic system checks are disabled in Settings, opening the plugin
  or entering Dashboard or My System runs a read-only update check.
  Their manual check/refresh controls always run that check
  against configured package mirrors; it does not install anything. Development
  checkout updates are not checked. Errors are shown rather than treated as
  confirmation that the system is up to date. When an Omarchy package update
  is reported, either update button opens Omarchy's full system update in a
  terminal for confirmation. Refresh My System after the update finishes.
  Launcher diagnostics are stored in `update-launch.log` beside the plugin's
  state file if the terminal does not open.
- **Saved** keeps items from any source available after they leave a feed.
- Every item section, including Saved, offers **Mark all read** and **Mark all
  unread** for all loaded items in that section, including filtered-out items.
  Read state is shared between a feed and its saved copies. Items that were
  visible and then scrolled completely above the list are marked read after
  1 second; scrolling back to them cancels the pending change. Skipped,
  never-visible rows are not marked. Closing the view or changing its filters
  cancels pending changes. This behavior can be disabled under Settings →
  Appearance.
  Read items use the theme's muted secondary color for their card borders;
  marking an item unread restores the primary borders. Thumbnails have no border.
  Read-status updates preserve the list's scroll position.
  Dashboard provides the same actions for all loaded feed and Saved items,
  and also marks viewed briefing items read after scrolling past them.
- **Settings** groups appearance/reading, refresh, dashboard, and section
  preferences in its own left navigation, showing only the selected category.
  On narrow panels the category navigation shows icons with label tooltips.
  Choose comfortable or compact rows (compact hides excerpts),
  disable preview loading, or turn off marking items read when opened or
  scrolled past.
  Dashboard panels can be hidden/reordered, with configurable item counts,
  included catch-up sources, and a new-only mode.
  Refresh-on-open has a master switch and individual source switches; manual
  Refresh still checks all sources. Scheduled feed refresh is enabled by
  default every 30 minutes and can be disabled or set to 10, 15, 20, 30, 45,
  or 60 minutes. It runs only after feeds have been loaded, while the shell is
  running, and respects the source switches. YouTube is excluded by default
  from scheduled refresh to limit network use, but can be enabled separately.
  Scheduled checks never query package mirrors or install updates. A grouped
  desktop notification lists the sections where a refresh found new items;
  notifications can be disabled in Settings → Refresh. Automatic system checks
  can be disabled independently.
  Each section can remember its query, up to 16 filter chips, and date selection
  across restarts. Disabling remembering deletes stored filters but leaves the
  current session unchanged. Group resets preserve saved items/read history;
  a section reset also clears that section's filters. YouTube's result limit
  remains configurable. Settings → Saved also offers **Remove all saved items**,
  with confirmation. This removes all bookmarks, including filtered-out items,
  without clearing read history or cached feeds.

Marketplace entries open their public listing or upstream GitHub repository.
This plugin does not install plugins or themes.

## Sources and network use

The plugin contacts these fixed HTTPS sources when opened (if refresh-on-open
and that source are enabled), on the configured periodic schedule (if enabled
and that source is enabled; YouTube is opt-in), or when **Refresh** is selected:

- `https://plugins.omarchy.org/catalog.json`
- `https://omarchy.org/themes/`
- `https://omarchy.org/news/rss.xml`
- `https://api.github.com/repos/omacom/omarchy/releases?per_page=100`
- `https://omarchy.org/data/search-index.json`
- `https://omarchy.org/manual/hotkeys/`
- `https://raw.githubusercontent.com/deepakness/omarchy-hub/main/data/resources.json`
- `https://omarchy.org/meetups/`
- YouTube search through the installed `yt-dlp`

While browsing, visible rows load previews from the plugin marketplace,
`i.ytimg.com`, or `omarchy.org`, when available, including meetup images. Previously saved theme
previews can still refer to the former theme preview CDN.

Catalog responses are limited to 32 MiB and listings to 10,000 items per
source. If the official themes page is unavailable, cached entries remain
visible with an error message.
Community and event links can point to third-party HTTPS sites; they are opened
only when selected. The plugin does not fetch community previews.
Releases include at most the 100 most recent GitHub releases and are subject to
GitHub's unauthenticated API rate limit. Cached releases remain available if
the API is unavailable or rate-limited.
YouTube search is limited to 50, 100, or 150 results and requires `yt-dlp`.
YouTube supplies approximate dates for search results, so date filtering near
period boundaries is approximate. Search indexing and these limits mean the
results are not a complete archive. Items without a date appear only under
All time. Refresh after changing the YouTube result limit.

Read status, saved items, settings, and cached listings are stored locally in
``${XDG_STATE_HOME:-~/.local/state}/all-things-omarchy/state.json`. Display
preferences are stored beside it in `display.json`. Search text
is local and is not sent to the sources. The plugin does not run background
refreshes, install downloaded content, or use credentials.

## Install and remove

Requires Omarchy's Quickshell-based shell with plugin support. Install the
repository, then enable its bar widget:

```sh
omarchy plugin add https://github.com/kelmankenberg/All-Things-Omarchy.git
omarchy plugin enable kel.all-things-omarchy right
```

Disable the widget without uninstalling it:

```sh
omarchy plugin disable kel.all-things-omarchy
```

Remove the installed plugin:

```sh
omarchy plugin remove kel.all-things-omarchy
```

Removal retains saved items, read history, and preferences in the local state
directory documented above. No shell configuration is overwritten by an
installer script.

The plugin requires the Omarchy Quickshell and Python 3. Searching YouTube
requires `yt-dlp`; it is not installed automatically. The package update check
requires `checkupdates` from `pacman-contrib` and uses its temporary package database.

## Test

```sh
python3 -m unittest discover -s tests
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -import tests/mocks -input tests
omarchy plugin validate .
qmllint -I "$OMARCHY_PATH/shell" BarWidget.qml AppContent.qml
```

## License

MIT; see [LICENSE](LICENSE).
