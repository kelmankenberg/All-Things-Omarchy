# Changelog

## Unreleased

### Added

- Automatic background feed refresh, enabled by default every 30 minutes.
  Settings supports 10, 15, 20, 30, 45, or 60 minutes and disabling scheduled
  refresh. Source switches are respected; YouTube is opt-in, and scheduled
  refresh never checks system packages or installs updates.
- Grouped desktop notifications showing which sections have newly discovered
  items and their counts, with an opt-out under Settings > Refresh.
- A highlighted bar icon and per-section badges for new items.
- Mark all read and Mark all unread actions for every item section, including
  Saved and Dashboard. Section actions include filtered-out loaded items;
  Dashboard actions cover all loaded feed and Saved items.
- Automatic read marking one second after a visible item is scrolled completely
  above the list, including Dashboard briefing items. Scrolling back cancels the
  pending change. This can be disabled under Settings > Appearance.
- A draggable navigation divider with a 160-220 pixel expanded-width range.
  The chosen width persists between sessions; collapsed navigation remains
  52 pixels. Widths follow interface scaling.

### Changed

- Moved the bulk read/unread actions to the right of each section title.
- Read item cards and Dashboard item dividers use the theme's muted secondary
  color. Marking an item unread restores the primary border color.
- Removed thumbnail borders from feed items and theme previews.

### Fixed

- Read-status updates no longer reset feed lists to the top; Dashboard updates
  also preserve the scroll position.
- New-item indicators remain across refreshes until the items are marked read.
- Initial state loads and refreshes without new discoveries do not trigger
  desktop notifications; items already marked new do not trigger repeat alerts.
