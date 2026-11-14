# Changelog

## 0.2.1 - 2026-11-14

### Fixed

- Filter fields no longer request native clipboard contents automatically.
  Keyboard editing and filter chips remain available; native clipboard paste
  and input-method composition are disabled for this field.
- Helper operations now have whole-operation deadlines and exactly-once
  completion, including failed starts, so busy indicators cannot remain stuck.
- Subprocess output and local state reads are bounded before buffering or
  parsing. State access enforces private, owner-controlled paths and serializes
  read-modify-write transactions.
- Feed previews are downloaded through a bounded, validated local cache instead
  of unbounded native image transfers, with failures shown in the plugin.

## 0.2.0 - 2026-11-13

### Added

- Bug report and feature request forms on GitHub, accessible from Settings →
  Help & About. The installed manifest version is displayed and prefilled in
  both forms; no diagnostics are uploaded automatically.
- A root `preview.png` screenshot of the Dashboard for the marketplace listing.
- A Settings → Sections category to show or hide optional feed, reference, and
  system sections. Hidden sections disappear from navigation and Dashboard
  surfaces, pause all feed and system refreshes, and hide their detailed
  settings. Cached data and saved items are preserved; Dashboard, Saved, and
  Settings remain available.
  Visibility preferences persist between sessions. Showing a section restores
  its cached content and existing preferences.
- Automatic background feed refresh, enabled by default every 30 minutes.
  Settings supports 10, 15, 20, 30, 45, or 60 minutes and disabling scheduled
  refresh. Source switches are respected; YouTube is opt-in, and scheduled
  refresh never checks system packages or installs updates.
- Grouped desktop notifications showing which sections have newly discovered
  items and their counts, with an opt-out under Settings > Refresh.
- A highlighted bar icon and per-section badges for new items.
- Mark all read and Mark all unread actions for every item section, including
  Saved and Dashboard. Section actions include filtered-out loaded items;
  Dashboard actions cover all loaded enabled-feed and Saved items.
- Automatic read marking one second after a visible item is scrolled completely
  above the list, including Dashboard briefing items. Scrolling back cancels the
  pending change. This can be disabled under Settings > Appearance.
- A draggable navigation divider with a 160-220 pixel expanded-width range.
  The chosen width persists between sessions; collapsed navigation remains
  52 pixels. Widths follow interface scaling.

### Changed

- Replaced the bar's hub icon with four outlined dashboard tiles. New items
  fill the tiles with the theme accent color and trigger a subtle animated
  quarter-turn with two-second pauses. Rotation respects disabled animations;
  the tooltip retains the exact new-item count.
- Hiding the currently viewed section returns the view to Dashboard. If a
  hidden section's detailed settings are open, Settings returns to Sections.
- Hidden sections are excluded from manual, on-open, and scheduled refreshes,
  source notifications, Dashboard source errors, and freshness listings.
  Hiding My System also disables its automatic checks and Dashboard panel.
- Refresh and Dashboard settings omit controls for hidden sections until they
  are shown again. Saved items from hidden sections remain accessible.
- Moved the bulk read/unread actions to the right of each section title.
- Read item cards and Dashboard item dividers use the theme's muted secondary
  color. Marking an item unread restores the primary border color.
- Removed thumbnail borders from feed items and theme previews.

### Fixed

- Dashboard bulk read/unread actions leave hidden feeds' unsaved items unchanged,
  while still including bookmarks from hidden feeds through Saved.
- Corrected the network disclosure to document scheduled background refreshes,
  their default frequency, opt-out controls, and hidden-section exclusions.
- Read-status updates no longer reset feed lists to the top; Dashboard updates
  also preserve the scroll position.
- New-item indicators remain across refreshes until the items are marked read.
- Initial state loads and refreshes without new discoveries do not trigger
  desktop notifications; items already marked new do not trigger repeat alerts.
