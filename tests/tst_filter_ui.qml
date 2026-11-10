import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtTest
import qs.Commons as Commons
import ".." as Plugin

TestCase {
  id: testCase
  name: "FilterUi"
  width: 760
  height: 660
  visible: true
  when: windowShown
  property int systemRequests: 0
  property string selectedTheme: ""
  property int updateRequests: 0
  property string lastMutation: ""
  property var fixtureModel
  property int refreshRequests: 0
  property string lastSetting: ""
  property string lastReset: ""
  property string openedUrl: ""
  property int clearSavedRequests: 0

  Plugin.AppContent {
    id: app
    anchors.fill: parent
    model: ({
      items: {
        plugins: [
          testCase.item("Dark Ocean", "Alice", "plugins"),
          testCase.item("Dark Forest", "Bob", "plugins"),
          testCase.item("Light Ocean", "Alice", "plugins")
        ],
        themes: [testCase.item("Dark theme", "Alice", "themes")],
        community: [testCase.item("Community app", "Alice", "community")],
        events: [
          Object.assign(testCase.item("Past", "", "events"), { timestamp: 100 }),
          Object.assign(testCase.item("Later", "", "events"), { timestamp: 300 }),
          Object.assign(testCase.item("Soon", "", "events"), { timestamp: 200 })
        ]
      }
    })
    translations: QtObject {
      function t(key) { return key + " %1 %2" }
      function tn(key, count) { return t(key) }
    }
    onQueryChanged: function(section, value) {
      var next = Object.assign({}, queries)
      next[section] = value
      queries = next
    }
    onFilterTermsEdited: function(section, value) {
      var next = Object.assign({}, filterTerms)
      next[section] = value
      filterTerms = next
    }
    onNavigationToggleRequested: navigationCollapsed = !navigationCollapsed
    onSystemRequested: testCase.systemRequests++
    onThemeSelected: function(name) { testCase.selectedTheme = name }
    onUpdateRequested: testCase.updateRequests++
    onRefreshRequested: testCase.refreshRequests++
    onOpenUrlRequested: function(url) { testCase.openedUrl = url }
    onSettingsResetRequested: function(group) { testCase.lastReset = group }
    onClearSavedRequested: testCase.clearSavedRequests++
    onSettingChanged: function(key, value) {
      testCase.lastSetting = key + ":" + value
      var next = Object.assign({}, model.settings || {})
      next[key] = value === "true" ? true : value === "false" ? false
        : key.endsWith("Limit") || key === "navigationWidth" ? Number(value) : value
      model = Object.assign({}, model, { settings: next })
    }
    onMutationRequested: function(action, itemId) { testCase.lastMutation = action + ":" + itemId }
  }

  function item(name, author, kind) {
    return { id: kind + ":" + name, name: name, author: author, kind: kind, timestamp: 0,
      source: "", summary: "", url: "", thumbnail: "", isRead: false,
      isNew: false, isSaved: false }
  }

  function init() {
    testCase.width = 760
    testCase.Window.window.width = 760
    app.model = fixtureModel
    app.queries = ({})
    app.filterTerms = ({})
    app.navigationCollapsed = false
    app.currentSettingsSection = "general"
    app.busy = false
    app.readingActive = true
    app.currentTime = 150000
    app.systemData = ({})
    app.themeData = ({})
    app.themeBusy = false
    app.themeError = ""
    app.systemBusy = false
    app.systemError = ""
    app.updateLaunching = false
    app.updatePending = false
    app.updateError = ""
    app.updateLog = ""
    testCase.systemRequests = 0
    testCase.selectedTheme = ""
    testCase.updateRequests = 0
    testCase.lastMutation = ""
    testCase.refreshRequests = 0
    testCase.lastSetting = ""
    testCase.lastReset = ""
    testCase.openedUrl = ""
    testCase.clearSavedRequests = 0
    app.setSection("plugins")
  }

  function initTestCase() {
    fixtureModel = app.model
    testCase.Window.window.width = 760
    testCase.Window.window.height = 660
  }

  function enterText(value) {
    var input = findChild(app, "filterInput")
    verify(input !== null)
    input.forceActiveFocus()
    for (var index = 0; index < value.length; ++index)
      keyClick(value.charAt(index).toUpperCase().charCodeAt(0))
    return input
  }

  function test_bulk_read_controls_use_section_even_with_active_filters() {
    app.queries = ({ plugins: "No matches" })
    compare(app.sectionItems("plugins").length, 0)
    var read = findChild(app, "markAllRead")
    var unread = findChild(app, "markAllUnread")
    verify(read.visible && read.enabled && unread.enabled)
    read.clicked()
    compare(lastMutation, "mark-all-read:plugins")
    unread.clicked()
    compare(lastMutation, "mark-all-unread:plugins")
    app.busy = true
    verify(!read.enabled && !unread.enabled)
    app.busy = false
    app.setSection("manual")
    verify(read.visible && !read.enabled)
    app.setSection("saved")
    verify(read.visible && !read.enabled)
    app.setSection("dashboard")
    verify(read.visible && read.enabled)
    read.clicked()
    compare(lastMutation, "mark-all-read:dashboard")
    unread.clicked()
    compare(lastMutation, "mark-all-unread:dashboard")
    app.setSection("settings")
    verify(!read.visible)
  }

  function prepareScrollReading(settings) {
    var rows = []
    for (var index = 0; index < 30; index++)
      rows.push(item("Row " + index, "", "plugins"))
    app.model = ({ items: { plugins: rows }, settings: settings || ({}) })
    var list = findChild(app, "listingScroll")
    verify(list !== null)
    list.forceLayout()
    list.positionViewAtBeginning()
    wait(50)
    return list
  }

  function test_bulk_read_actions_align_right_in_the_section_title_row() {
    var header = findChild(app, "sectionHeader")
    var title = findChild(app, "sectionHeading")
    var read = findChild(app, "markAllRead")
    var unread = findChild(app, "markAllUnread")
    tryVerify(function() {
      var titleCenter = title.mapToItem(header, 0, title.height / 2)
      var readCenter = read.mapToItem(header, 0, read.height / 2)
      var unreadEnd = unread.mapToItem(header, unread.width, unread.height / 2)
      return Math.abs(titleCenter.y - readCenter.y) <= 1
        && Math.abs(titleCenter.y - unreadEnd.y) <= 1
        && Math.abs(unreadEnd.x - header.width) <= 1
        && title.mapToItem(header, title.width, 0).x <= readCenter.x
    })
  }

  function dragNavigationBy(delta) {
    var handle = findChild(app, "navigationResizeHandle")
    var start = handle.mapToItem(app, handle.width / 2, handle.height / 2)
    mousePress(app, start.x, start.y)
    mouseMove(app, start.x + delta, start.y, 30)
    mouseRelease(app, start.x + delta, start.y)
  }

  function test_navigation_width_drag_is_bounded_saved_and_restored() {
    var panel = findChild(app, "navigationPanel")
    var handle = findChild(app, "navigationResizeHandle")
    tryCompare(panel, "width", 160)
    dragNavigationBy(40)
    tryCompare(panel, "width", 200)
    compare(lastSetting, "navigationWidth:200")
    compare(app.model.settings.navigationWidth, 200)
    dragNavigationBy(100)
    tryCompare(panel, "width", 220)
    compare(lastSetting, "navigationWidth:220")
    app.navigationCollapsed = true
    tryCompare(panel, "width", 52)
    verify(!handle.visible)
    app.navigationCollapsed = false
    tryCompare(panel, "width", 220)
    dragNavigationBy(-200)
    tryCompare(panel, "width", 160)
    compare(lastSetting, "navigationWidth:160")
    app.model = Object.assign({}, app.model, { settings: { navigationWidth: 190 } })
    tryCompare(panel, "width", 190)
    app.busy = true
    verify(!handle.enabled)
  }

  function test_scrolling_past_visible_rows_marks_read_after_one_second() {
    var list = prepareScrollReading()
    var first = list.itemAtIndex(0)
    verify(first !== null)
    var id = first.modelData.id
    list.contentY = first.y + first.height + 5
    wait(500)
    compare(lastMutation, "")
    tryVerify(function() { return lastMutation.indexOf("mark-read-items:") === 0 }, 1000)
    var ids = JSON.parse(lastMutation.substring("mark-read-items:".length))
    verify(ids.indexOf(id) >= 0)
    verify(ids.indexOf("plugins:Row 29") < 0)
  }

  function test_scrolling_back_cancels_pending_read() {
    var list = prepareScrollReading()
    var first = list.itemAtIndex(0)
    list.contentY = first.y + first.height + 5
    wait(350)
    list.positionViewAtBeginning()
    wait(1100)
    compare(lastMutation, "")
  }

  function test_read_updates_preserve_feed_scroll_position() {
    var list = prepareScrollReading()
    list.contentY = 280
    wait(50)
    var position = list.contentY
    var visibleIndex = list.indexAt(10, position + 10)
    verify(visibleIndex >= 0)
    var visibleRow = list.itemAtIndex(visibleIndex)
    var originalItems = app.model.items.plugins
    var changed = originalItems.map(function(entry, index) {
      return Object.assign({}, entry, { isRead: index === 0, isSaved: index === 1 })
    })
    app.model = Object.assign({}, app.model, { items: { plugins: changed } })
    list.forceLayout()
    wait(50)
    compare(list.contentY, position)
    compare(list.itemAtIndex(visibleIndex), visibleRow)
  }

  function test_read_updates_preserve_dashboard_scroll_position() {
    var rows = []
    for (var index = 0; index < 12; index++)
      rows.push(item("Dashboard " + index, "", "plugins"))
    app.model = ({ items: { plugins: rows },
      settings: { dashboard_system: false, dashboard_events: false, dashboard_saved: false } })
    app.setSection("dashboard")
    var dashboard = findChild(app, "dashboardPage")
    wait(80)
    dashboard.contentItem.contentY = 250
    wait(50)
    var position = dashboard.contentItem.contentY
    var panel = findChild(app, "dashboardPanel_catchup")
    app.model = Object.assign({}, app.model, { items: { plugins: rows.map(function(entry, index) {
      return Object.assign({}, entry, { isRead: index === 0 })
    }) } })
    wait(80)
    compare(dashboard.contentItem.contentY, position)
    compare(findChild(app, "dashboardPanel_catchup"), panel)
  }

  function test_dashboard_items_are_marked_after_scrolling_past_them() {
    var rows = []
    for (var index = 0; index < 12; index++)
      rows.push(item("Dashboard " + index, "", "plugins"))
    app.model = ({ items: { plugins: rows },
      settings: { dashboard_system: false, dashboard_events: false, dashboard_saved: false } })
    app.setSection("dashboard")
    var dashboard = findChild(app, "dashboardPage")
    wait(80)
    var firstTitle = findChild(app, "briefingTitle_plugins:Dashboard 0")
    verify(firstTitle !== null)
    var row = firstTitle.parent
    var bottom = row.mapToItem(dashboard.contentItem.contentItem, 0, row.height).y
    dashboard.contentItem.contentY = bottom + 5
    wait(500)
    compare(lastMutation, "")
    tryVerify(function() { return lastMutation.indexOf("mark-read-items:") === 0 }, 1000)
    var ids = JSON.parse(lastMutation.substring("mark-read-items:".length))
    verify(ids.indexOf("plugins:Dashboard 0") >= 0)
    verify(ids.indexOf("plugins:Dashboard 11") < 0)
  }

  function test_scroll_read_waits_for_busy_work_and_cancels_when_hidden() {
    var list = prepareScrollReading()
    app.busy = true
    var first = list.itemAtIndex(0)
    list.contentY = first.y + first.height + 5
    wait(1200)
    compare(lastMutation, "")
    app.busy = false
    tryVerify(function() { return lastMutation.indexOf("mark-read-items:") === 0 }, 500)
    list.positionViewAtBeginning()
    wait(50)
    lastMutation = ""
    list.contentY = first.y + first.height + 5
    app.readingActive = false
    wait(1200)
    compare(lastMutation, "")
  }

  function test_scroll_read_opt_out_and_filter_changes_do_not_mark_items() {
    var list = prepareScrollReading({ markReadOnScroll: false })
    var first = list.itemAtIndex(0)
    list.contentY = first.y + first.height + 5
    wait(1200)
    compare(lastMutation, "")
    app.model = Object.assign({}, app.model, { settings: { markReadOnScroll: true } })
    list.positionViewAtBeginning()
    wait(50)
    first = list.itemAtIndex(0)
    list.contentY = first.y + first.height + 5
    app.queries = ({ plugins: "Row 29" })
    wait(1200)
    compare(lastMutation, "")
  }

  function test_termsCanBeAddedRemovedAndKeptPerSection() {
    var input = enterText("dark")
    var initialHeight = input.height
    compare(app.sectionItems("plugins").length, 2)
    keyClick(Qt.Key_Return)
    compare(app.filterTerms.plugins.join("|"), "dark")
    compare(input.text, "")
    var viewport = findChild(app, "filterTermsViewport")
    compare(viewport.parent, input)
    compare(input.height, initialHeight)
    verify(viewport.visible && viewport.height <= input.height)
    verify(input.leftPadding > viewport.width)

    input = enterText("alice")
    compare(input.text, "alice")
    var add = findChild(app, "addFilterButton")
    verify(add.enabled)
    wait(50)
    verify(add.width > 0 && add.height > 0)
    mouseClick(add)
    compare(app.filterTerms.plugins.join("|"), "dark|alice")
    compare(app.sectionItems("plugins").length, 1)

    app.setSection("themes")
    compare(app.sectionItems("themes").length, 1)
    enterText("theme")
    keyClick(Qt.Key_Return)
    app.setSection("plugins")
    compare(app.filterTerms.plugins.join("|"), "dark|alice")
    compare(app.filterTerms.themes.join("|"), "theme")

    wait(50)
    var remove = findChild(app, "removeFilterButton_0")
    verify(remove !== null)
    mouseClick(remove)
    compare(app.filterTerms.plugins.join("|"), "alice")
    compare(app.sectionItems("plugins").length, 2)
  }

  function test_overflowKeepsTextEntryAndEarlierTermsAccessible() {
    app.filterTerms = ({ plugins: ["first long term", "second long term", "third long term"] })
    wait(50)
    var input = findChild(app, "filterInput")
    var viewport = findChild(app, "filterTermsViewport")
    verify(viewport.contentWidth > viewport.width)
    verify(viewport.contentX > 0)
    verify(input.leftPadding < input.width)
    enterText("dark")
    compare(input.text, "dark")
    viewport.contentX = 0
    wait(50)
    mouseClick(findChild(app, "removeFilterButton_0"))
    compare(app.filterTerms.plugins.join("|"), "second long term|third long term")
  }

  function test_backspaceRemovesLastTermOnlyAtStartOfText() {
    app.filterTerms = ({ plugins: ["dark", "alice"], themes: ["theme"] })
    var input = enterText("cat")
    keyClick(Qt.Key_Backspace)
    compare(input.text, "ca")
    compare(app.filterTerms.plugins.join("|"), "dark|alice")

    input.select(2, 0)
    keyClick(Qt.Key_Backspace)
    compare(input.text, "")
    compare(app.filterTerms.plugins.join("|"), "dark|alice")

    enterText("ca")
    input.cursorPosition = 0
    keyClick(Qt.Key_Backspace)
    compare(input.text, "ca")
    compare(app.filterTerms.plugins.join("|"), "dark")
    compare(app.filterTerms.themes.join("|"), "theme")

    keyClick(Qt.Key_Backspace)
    compare(app.filterTerms.plugins.length, 0)
    keyClick(Qt.Key_Backspace)
    compare(input.text, "ca")
  }

  function test_toolbarAndCollapsedNavigation() {
    var toolbar = findChild(app, "topToolbar")
    var title = findChild(app, "toolbarTitle")
    var refresh = findChild(app, "toolbarRefreshButton")
    var toggle = findChild(app, "navigationToggleButton")
    var panel = findChild(app, "navigationPanel")
    wait(50)
    compare(toolbar.width, app.width)
    compare(title.text, app.t("brand"))
    verify(toggle.mapToItem(toolbar, 0, 0).x < title.mapToItem(toolbar, 0, 0).x)
    verify(title.mapToItem(toolbar, 0, 0).x < refresh.mapToItem(toolbar, 0, 0).x)
    var expandedWidth = panel.width
    mouseClick(toggle)
    wait(50)
    verify(app.navigationCollapsed)
    verify(panel.width < expandedWidth)
    var themes = findChild(app, "navigationButton_themes")
    verify(themes.iconOnly)
    compare(themes.text, app.sectionIcons.themes)
    compare(themes.ToolTip.text, app.sectionTitle("themes"))
    mouseClick(themes)
    compare(app.currentSection, "themes")
    mouseClick(toggle)
    wait(50)
    verify(!app.navigationCollapsed)
    compare(panel.width, expandedWidth)
    verify(!themes.iconOnly)
  }

  function test_navigation_is_borderless_and_highlights_on_hover() {
    var themes = findChild(app, "navigationButton_themes")
    var toolbar = findChild(app, "topToolbar")
    verify(themes !== null)
    mouseMove(toolbar, 10, 10)
    wait(30)
    compare(themes.background.border.width, 0)
    compare(themes.background.color.a, 0)
    mouseMove(themes, themes.width / 2, themes.height / 2)
    tryVerify(function() { return themes.hovered })
    verify(themes.background.color.a > 0)
    compare(themes.background.border.width, 0)
    mouseMove(toolbar, 10, 10)
    tryVerify(function() { return !themes.hovered })
    compare(themes.background.color.a, 0)

    app.navigationCollapsed = true
    wait(30)
    mouseMove(themes, themes.width / 2, themes.height / 2)
    tryVerify(function() { return themes.hovered })
    verify(themes.background.color.a > 0)
    compare(themes.background.border.width, 0)
  }

  function test_saved_navigation_count_updates_in_both_modes() {
    var original = app.model
    var saved = findChild(app, "navigationButton_saved")
    var badge = findChild(saved, "savedCountBadge")
    verify(saved !== null && badge !== null)
    compare(saved.text, app.sectionTitle("saved") + "  0")
    app.model = Object.assign({}, original, {
      items: Object.assign({}, original.items, {
        saved: [testCase.item("One", "Alice", "plugins"), testCase.item("Two", "Bob", "themes")]
      })
    })
    compare(saved.text, app.sectionTitle("saved") + "  2")
    verify(saved.ToolTip.text.indexOf("2") >= 0)
    verify(!badge.visible)
    app.navigationCollapsed = true
    compare(saved.text, app.sectionIcons.saved)
    verify(badge.visible)
    compare(findChild(badge, "savedBadgeText").text, "2")
    app.model = Object.assign({}, original, { items: Object.assign({}, original.items, { saved: [] }) })
    verify(!badge.visible)
    app.navigationCollapsed = false
    compare(saved.text, app.sectionTitle("saved") + "  0")
    app.model = original
  }

  function test_read_borders_follow_theme_and_revert_when_marked_unread() {
    var entry = item("Border state", "", "plugins")
    app.model = ({ items: { plugins: [entry] } })
    var list = findChild(app, "listingScroll")
    list.forceLayout()
    var card = list.itemAtIndex(0)
    verify(card !== null)
    compare(card.border.color, Qt.color(Commons.Color.popups.border))
    compare(findChild(card, "itemPreview").border.width, 0)

    app.model = ({ items: { plugins: [Object.assign({}, entry, { isRead: true })] } })
    list.forceLayout()
    card = list.itemAtIndex(0)
    compare(card.border.color, Commons.Color.muted)
    compare(findChild(card, "itemPreview").border.width, 0)
    var originalMuted = Commons.Color.muted
    try {
      Commons.Color.muted = "#99bbaa"
      compare(card.border.color, Commons.Color.muted)
      compare(findChild(card, "itemPreview").border.width, 0)
    } finally {
      Commons.Color.muted = originalMuted
    }

    app.model = ({ items: { plugins: [entry] } })
    list.forceLayout()
    card = list.itemAtIndex(0)
    compare(card.border.color, Qt.color(Commons.Color.popups.border))
    compare(findChild(card, "itemPreview").border.width, 0)

    app.setSection("dashboard")
    var eventId = fixtureModel.items.events[1].id
    app.model = fixtureModel
    var divider = findChild(app, "briefingBorder_" + eventId)
    verify(divider !== null)
    compare(divider.color, Qt.color(Commons.Color.popups.border))
    app.model = Object.assign({}, fixtureModel, { items: Object.assign({}, fixtureModel.items, {
      events: fixtureModel.items.events.map(function(event) {
        return Object.assign({}, event, { isRead: true })
      })
    }) })
    divider = findChild(app, "briefingBorder_" + eventId)
    compare(divider.color, Commons.Color.muted)
    app.model = fixtureModel
    divider = findChild(app, "briefingBorder_" + eventId)
    compare(divider.color, Qt.color(Commons.Color.popups.border))
  }

  function test_item_actions_are_borderless_and_highlight_on_hover() {
    var toolbar = findChild(app, "topToolbar")
    var names = ["itemOpenButton", "itemSaveButton", "itemReadButton"]
    for (var index = 0; index < names.length; ++index) {
      var button = findChild(app, names[index])
      verify(button !== null && button.visible)
      mouseMove(toolbar, 10, 10)
      wait(30)
      compare(button.background.border.width, 0)
      compare(button.background.color.a, 0)
      mouseMove(button, button.width / 2, button.height / 2)
      tryVerify(function() { return button.hovered })
      verify(button.background.color.a > 0)
    }
    var saveButton = findChild(app, "itemSaveButton")
    mouseClick(saveButton)
    verify(testCase.lastMutation.indexOf("toggle-saved:plugins:") === 0)
    var readButton = findChild(app, "itemReadButton")
    mouseClick(readButton)
    verify(testCase.lastMutation.indexOf("toggle-read:plugins:") === 0)
    app.busy = true
    verify(!saveButton.enabled && !readButton.enabled)
    verify(findChild(app, "openSourceButton").background.border.width > 0)
  }

  function test_new_sections_support_filters_navigation_and_system_errors() {
    app.setSection("community")
    enterText("app")
    compare(app.sectionItems("community").length, 1)
    app.setSection("events")
    compare(app.sectionItems("events").map(function(row) { return row.name }).join("|"), "Soon|Later|Past")
    app.navigationCollapsed = true
    wait(50)
    var systemButton = findChild(app, "navigationButton_system")
    compare(systemButton.ToolTip.text, app.sectionTitle("system"))
    app.setSection("system")
    compare(testCase.systemRequests, 1)
    app.systemData = ({
      version: { value: "4.5", error: "" },
      update: { status: "unknown", detail: "Network failed" }
    })
    app.themeData = ({ current: { value: "", error: "Theme unavailable" }, themes: [] })
    wait(50)
    compare(findChild(app, "systemValue_version").text, "4.5")
    compare(findChild(app, "systemValue_theme").text, "Theme unavailable")
    compare(findChild(app, "systemValue_update").text, "Network failed")
    compare(findChild(app, "systemValue_update").textFormat, Text.PlainText)
  }

  function test_theme_dropdown_applies_selection_and_tracks_actual_theme() {
    app.themeData = ({
      current: { value: "Current", error: "" },
      themes: ["Current", "Tokyo Night", "<b>literal</b>"],
      previews: { "Current": String(Qt.resolvedUrl("preview.svg")) },
      listError: "", actionError: "", warning: ""
    })
    app.setSection("system")
    wait(50)
    var combo = findChild(app, "systemThemeCombo")
    verify(combo !== null && combo.visible && combo.enabled)
    compare(combo.currentIndex, 0)
    compare(findChild(combo, "themeCurrentText").textFormat, Text.PlainText)
    var preview = findChild(combo, "themeCurrentPreview")
    compare(preview.imageUrl, String(Qt.resolvedUrl("preview.svg")))
    tryCompare(findChild(preview, "thumbnailImage"), "status", Image.Ready)
    verify(!findChild(preview, "thumbnailFallback").visible)
    combo.forceActiveFocus()
    keyClick(Qt.Key_Space)
    tryVerify(function() { return combo.popup.visible })
    var listedPreview = findChild(combo.popup.contentItem, "themeOptionPreview_0")
    verify(listedPreview !== null)
    compare(listedPreview.imageUrl, String(Qt.resolvedUrl("preview.svg")))
    tryCompare(findChild(listedPreview, "thumbnailImage"), "status", Image.Ready)
    var fallback = findChild(combo.popup.contentItem, "themeOptionPreview_1")
    verify(fallback !== null)
    verify(findChild(fallback, "thumbnailFallback").visible)
    keyClick(Qt.Key_Down)
    keyClick(Qt.Key_Return)
    compare(testCase.selectedTheme, "Tokyo Night")
    compare(combo.currentIndex, 0)
    app.themeData = ({
      current: { value: "Current", error: "" },
      themes: ["Current", "Tokyo Night", "<b>literal</b>"],
      listError: "", actionError: "Theme could not be applied", warning: ""
    })
    compare(combo.currentIndex, 0)
    compare(findChild(app, "systemThemeMessage").text, "Theme could not be applied")
    app.themeData = ({
      current: { value: "Tokyo Night", error: "" },
      themes: ["Current", "Tokyo Night", "<b>literal</b>"],
      listError: "", actionError: "", warning: ""
    })
    compare(combo.currentIndex, 1)
    app.themeBusy = true
    verify(!combo.enabled)
  }

  function test_update_buttons_require_a_confirmed_available_package_update() {
    app.setSection("system")
    app.systemData = ({
      version: { value: "4.5", error: "" },
      update: { status: "none", detail: "" }
    })
    wait(50)
    var versionButton = findChild(app, "systemUpdateButton_version")
    var packageButton = findChild(app, "systemUpdateButton_update")
    verify(versionButton !== null && packageButton !== null)
    verify(!versionButton.enabled && !packageButton.enabled)
    verify(findChild(app, "systemVersionUpdateStatus").text.indexOf("system.none") >= 0)

    app.systemData = ({
      version: { value: "4.5", error: "" },
      update: { status: "available", detail: "omarchy 4.5 -> 4.6" }
    })
    verify(versionButton.enabled && packageButton.enabled)
    verify(findChild(app, "systemVersionUpdateStatus").text.indexOf("system.versionAvailable") >= 0)
    mouseClick(versionButton)
    compare(testCase.updateRequests, 1)
    packageButton.clicked()
    compare(testCase.updateRequests, 2)

    app.updatePending = true
    verify(!versionButton.enabled && !packageButton.enabled)
    app.updatePending = false
    app.systemBusy = true
    verify(!versionButton.enabled && !packageButton.enabled)
    app.systemBusy = false
    app.systemError = "Network error"
    verify(!versionButton.enabled && !packageButton.enabled)
    app.systemError = ""
    app.systemData = ({ update: { status: "unknown", detail: "Network error" } })
    verify(!versionButton.enabled && !packageButton.enabled)
  }

  function test_dashboard_prioritizes_unread_discoveries_and_saved_queue() {
    var discovery = Object.assign(item("<b>New plugin</b>", "", "plugins"), { isNew: true })
    var read = Object.assign(item("Already read", "", "plugins"), { isNew: true, isRead: true })
    var recent = Object.assign(item("Recent news", "", "news"), { timestamp: 100 })
    var saved = Object.assign(item("Saved story", "", "news"), { isSaved: true })
    app.model = ({
      items: {
        plugins: [read, discovery], news: [recent], themes: [item("Undated", "", "themes")],
        saved: [read, saved], manual: [item("Reference", "", "manual")]
      }
    })
    app.queries = ({ plugins: "does not match" })
    app.dateRanges = ({ news: "today" })
    app.setSection("dashboard")
    compare(app.catchUpItems.map(function(row) { return row.name }).join("|"),
      "<b>New plugin</b>|Recent news|Undated")
    compare(app.readingQueue.length, 1)
    compare(app.readingQueue[0].id, saved.id)
    var title = findChild(app, "briefingTitle_" + discovery.id)
    verify(title !== null)
    compare(title.textFormat, Text.PlainText)
    compare(title.text, "<b>New plugin</b>")
    var save = findChild(app, "briefingSave_" + discovery.id)
    save.clicked()
    compare(lastMutation, "toggle-saved:" + discovery.id)
    var markRead = findChild(app, "briefingRead_" + discovery.id)
    markRead.clicked()
    compare(lastMutation, "toggle-read:" + discovery.id)
    var unsave = findChild(app, "briefingSave_" + saved.id)
    compare(unsave.text, app.t("actions.unsave"))
    unsave.clicked()
    compare(lastMutation, "toggle-saved:" + saved.id)
    app.busy = true
    verify(!save.enabled && !markRead.enabled && !unsave.enabled)
    app.busy = false
    app.model = ({ items: { plugins: [read], saved: [] } })
    compare(app.catchUpItems.length, 0)
    compare(app.readingQueue.length, 0)
    verify(findChild(app, "dashboardCaughtUp").visible)
    verify(findChild(app, "dashboardQueueEmpty").visible)

    var catalog = []
    for (var index = 0; index < 12; ++index)
      catalog.push(Object.assign(item("Plugin " + index, "", "plugins"), { timestamp: 1000 - index }))
    app.model = ({ items: { plugins: catalog, news: [recent], themes: [item("Theme", "", "themes")] } })
    compare(app.catchUpItems.slice(0, 3).map(function(row) { return row.name }).join("|"),
      "Plugin 0|Recent news|Theme")
  }

  function test_dashboard_events_expire_and_layout_adapts() {
    app.setSection("dashboard")
    compare(app.upcomingItems.map(function(row) { return row.name }).join("|"), "Soon|Later")
    verify(findChild(app, "briefingTitle_events:Past") === null)
    verify(app.eventDescription(app.upcomingItems[0]).indexOf("dashboard.inHours") >= 0)
    app.currentTime = 200000
    compare(app.upcomingItems.map(function(row) { return row.name }).join("|"), "Later")
    app.currentTime = 300000
    compare(app.upcomingItems.length, 0)
    verify(findChild(app, "dashboardNoEvents").visible)
    var grid = findChild(app, "briefingGrid")
    compare(grid.columns, 1)
    testCase.Window.window.width = 1200
    testCase.width = 1200
    tryCompare(grid, "columns", 2)
    testCase.Window.window.width = 760
    testCase.width = 760
    tryCompare(grid, "columns", 1)
    var dashboard = findChild(app, "dashboardPage")
    verify(dashboard.contentHeight > dashboard.height)
  }

  function test_dashboard_system_attention_retry_and_freshness() {
    app.model = Object.assign({}, fixtureModel, {
      lastFetched: { plugins: 100 },
      errors: { news: "<b>Network failed</b>" }
    })
    app.setSection("dashboard")
    compare(systemRequests, 1)
    var sourceAttention = findChild(app, "dashboardSourceAttention")
    verify(sourceAttention.visible)
    var retry = findChild(app, "dashboardRetrySourcesButton")
    retry.clicked()
    compare(refreshRequests, 1)
    app.busy = true
    verify(!retry.enabled)
    app.busy = false
    verify(findChild(app, "dashboardFreshness_plugins").text.indexOf("dashboard.refreshed") === 0)
    compare(findChild(app, "dashboardFreshness_news").text, app.t("dashboard.notRefreshed"))
    var status = findChild(app, "dashboardSystemStatus")
    compare(status.text, app.t("system.unknown"))
    compare(status.textFormat, Text.PlainText)
    var update = findChild(app, "dashboardUpdateButton")
    verify(!update.visible)
    app.systemData = ({ update: { status: "available", detail: "4.5 -> 4.6" } })
    verify(update.visible && update.enabled)
    update.clicked()
    compare(updateRequests, 1)
    app.updatePending = true
    verify(!update.enabled)
    app.updatePending = false
    app.systemBusy = true
    verify(!update.enabled)
    compare(status.text, app.t("system.checking"))
    app.systemBusy = false
    app.systemError = "<b>Check failed</b>"
    verify(!update.enabled)
    compare(status.text, "<b>Check failed</b>")
    findChild(app, "dashboardCheckSystemButton").clicked()
    compare(systemRequests, 2)
    app.systemError = ""
    app.systemData = ({ update: { status: "none", detail: "" } })
    verify(!update.visible)
    compare(status.text, app.t("system.none"))
    app.model = fixtureModel
    verify(!sourceAttention.visible)
  }

  function test_settings_controls_change_preview_density_and_read_behavior() {
    app.setSection("settings")
    var previews = findChild(app, "setting_showPreviews")
    verify(previews !== null && previews.checked)
    mouseClick(previews)
    compare(lastSetting, "showPreviews:false")
    findChild(app, "setting_density").activated(1)
    compare(lastSetting, "density:compact")
    findChild(app, "setting_markReadOnOpen").checked = false
    findChild(app, "setting_markReadOnOpen").toggled()
    compare(lastSetting, "markReadOnOpen:false")
    findChild(app, "reset_general").clicked()
    compare(lastReset, "general")
    app.setSection("plugins")
    verify(!findChild(app, "itemPreview").visible)
    verify(!findChild(app, "itemSummary").visible)
    var article = Object.assign(item("Open me", "", "news"), { url: "https://omarchy.org/news/" })
    app.openItem(article)
    compare(openedUrl, article.url)
    compare(lastMutation, "")
    app.model = Object.assign({}, app.model, {
      settings: Object.assign({}, app.model.settings, { markReadOnOpen: true })
    })
    app.openItem(article)
    compare(lastMutation, "mark-read:" + article.id)
  }

  function test_dashboard_preferences_control_order_visibility_counts_and_sources() {
    app.setSection("settings")
    findChild(app, "settingsNav_dashboard").clicked()
    findChild(app, "dashboardUp_saved").clicked()
    compare(lastSetting, "dashboardOrder:system,catchup,saved,events")
    findChild(app, "setting_catchUpLimit").activated(0)
    compare(lastSetting, "catchUpLimit:4")
    var items = []
    for (var index = 0; index < 10; ++index)
      items.push(item("P" + index, "", "plugins"))
    app.model = ({ items: { plugins: items }, settings: {
      dashboardOrder: "saved,events,catchup,system", dashboard_system: false, catchUpLimit: 4
    } })
    app.setSection("dashboard")
    verify(findChild(app, "dashboardPanel_system") === null)
    compare(app.catchUpItems.length, 10)
    compare(app.catchUpItems[3].id, "plugins:P3")
    var panel = findChild(app, "dashboardPanel_catchup")
    verify(panel !== null && panel.item !== null)
    tryVerify(function() { return findChild(app, "briefingTitle_plugins:P3") !== null })
    verify(findChild(app, "briefingTitle_plugins:P4") === null)
    compare(app.dashboardOrder[0], "saved")
    app.model = Object.assign({}, app.model, { settings: {
      dashboardSource_plugins: false, dashboardNewOnly: true
    } })
    compare(app.catchUpItems.length, 0)
    var newItem = Object.assign(items[0], { isNew: true })
    app.model = { items: { plugins: [newItem, items[1]] }, settings: { dashboardNewOnly: true } }
    compare(app.catchUpItems.length, 1)
  }

  function test_manual_system_checks_remain_available_with_automatic_checks_disabled() {
    app.model = Object.assign({}, app.model, { settings: { systemCheckOnOpen: false } })
    app.setSection("dashboard")
    compare(systemRequests, 0)
    findChild(app, "dashboardCheckSystemButton").clicked()
    compare(systemRequests, 1)
    app.setSection("system")
    compare(systemRequests, 1)
    findChild(app, "toolbarRefreshButton").clicked()
    compare(systemRequests, 2)
  }

  function test_new_item_badges_cover_sections_dashboard_saved_and_collapse() {
    var plugin = Object.assign(item("New plugin", "", "plugins"), { isNew: true })
    var saved = Object.assign(item("Saved new story", "", "news"), { isNew: true, isSaved: true })
    app.model = ({
      items: { plugins: [plugin], news: [], saved: [saved] },
      newCounts: { plugins: 2, news: 1, events: 3 }
    })
    var pluginBadge = findChild(app, "newCountBadge_plugins")
    var newsBadge = findChild(app, "newCountBadge_news")
    var eventsBadge = findChild(app, "newCountBadge_events")
    var dashboardBadge = findChild(app, "newCountBadge_dashboard")
    var savedBadge = findChild(app, "newCountBadge_saved")
    verify(pluginBadge.visible && newsBadge.visible && eventsBadge.visible)
    verify(dashboardBadge.visible && savedBadge.visible)
    compare(findChild(pluginBadge, "newBadgeText_plugins").text, "2")
    compare(findChild(eventsBadge, "newBadgeText_events").text, "3")
    compare(findChild(dashboardBadge, "newBadgeText_dashboard").text, "6")
    compare(findChild(savedBadge, "newBadgeText_saved").text, "1")
    verify(findChild(app, "navigationButton_plugins").description.indexOf("2") >= 0)
    app.navigationCollapsed = true
    verify(pluginBadge.visible && newsBadge.visible && savedBadge.visible)
    compare(findChild(app, "navigationButton_plugins").text, app.sectionIcons.plugins)
    app.model = ({ items: { plugins: [plugin], saved: [saved] }, newCounts: { plugins: 0 } })
    verify(!pluginBadge.visible && !dashboardBadge.visible && savedBadge.visible)
  }

  function test_periodic_refresh_preferences_default_to_thirty_and_bound_video_cost() {
    app.setSection("settings")
    findChild(app, "settingsNav_refresh").clicked()
    wait(50)
    var periodic = findChild(app, "setting_periodicRefresh")
    var interval = findChild(app, "setting_refreshInterval")
    var videos = findChild(app, "setting_periodicVideos")
    verify(periodic !== null && periodic.checked)
    verify(interval !== null)
    compare(interval.count, 6)
    compare(interval.currentIndex, 3)
    verify(videos !== null && !videos.checked)
    interval.activated(0)
    compare(lastSetting, "refreshInterval:10")
    periodic.checked = false
    periodic.toggled()
    compare(lastSetting, "periodicRefresh:false")
    videos.checked = true
    videos.toggled()
    compare(lastSetting, "periodicVideos:true")
    findChild(app, "reset_refresh").clicked()
    compare(lastReset, "refresh")
  }

  function test_settings_navigation_shows_only_selected_category_and_resets_scroll() {
    app.setSection("settings")
    verify(findChild(app, "setting_showPreviews") !== null)
    verify(findChild(app, "setting_refreshOnOpen") === null)
    verify(findChild(app, "setting_catchUpLimit") === null)
    var refresh = findChild(app, "settingsNav_refresh")
    wait(50)
    mouseClick(refresh)
    compare(app.currentSettingsSection, "refresh")
    verify(refresh.highlighted)
    verify(findChild(app, "setting_refreshOnOpen") !== null)
    tryVerify(function() { return findChild(app, "setting_showPreviews") === null })
    verify(findChild(app, "setting_remember_saved") === null)

    findChild(app, "settingsNav_dashboard").clicked()
    var scroll = findChild(app, "settingsContentScroll")
    tryVerify(function() { return scroll.contentHeight > scroll.height })
    scroll.contentItem.contentY = 80
    verify(scroll.contentItem.contentY > 0)
    findChild(app, "settingsNav_general").clicked()
    tryCompare(scroll.contentItem, "contentY", 0)
    verify(findChild(app, "setting_showPreviews") !== null)
    tryVerify(function() { return findChild(app, "setting_catchUpLimit") === null })

    findChild(app, "settingsNav_videos").clicked()
    verify(findChild(app, "setting_videosLimit").visible)
    verify(findChild(app, "setting_remember_videos") !== null)
    verify(findChild(app, "setting_remember_plugins") === null)
    findChild(app, "reset_videos").clicked()
    compare(lastReset, "videos")
    app.setSection("plugins")
    app.setSection("settings")
    compare(app.currentSettingsSection, "videos")
    verify(findChild(app, "setting_remember_videos") !== null)
    app.busy = true
    findChild(app, "settingsNav_saved").clicked()
    compare(app.currentSettingsSection, "saved")
    verify(!findChild(app, "setting_remember_saved").enabled)
    verify(!findChild(app, "setting_videosLimit").visible)
  }

  function test_settings_navigation_is_icon_only_on_narrow_panels() {
    app.setSection("settings")
    var navigation = findChild(app, "settingsNavigation")
    var themes = findChild(app, "settingsNav_themes")
    verify(themes.iconOnly)
    compare(themes.ToolTip.text, app.settingsSectionTitle("themes"))
    var narrowWidth = navigation.width
    testCase.width = 1200
    testCase.Window.window.width = 1200
    tryCompare(themes, "iconOnly", false)
    verify(navigation.width > narrowWidth)
    compare(themes.text, app.settingsSectionTitle("themes"))
    mouseClick(themes)
    compare(app.currentSettingsSection, "themes")
    verify(findChild(app, "setting_remember_themes") !== null)
  }

  function test_clear_saved_requires_confirmation_and_preserves_cancel() {
    app.model = ({ items: { saved: [
      Object.assign(item("One", "", "news"), { isSaved: true }),
      Object.assign(item("Two", "", "themes"), { isSaved: true })
    ] } })
    app.queries = ({ saved: "does not match" })
    compare(app.sectionItems("saved").length, 0)
    app.setSection("settings")
    findChild(app, "settingsNav_saved").clicked()
    var remove = findChild(app, "clearSavedButton")
    var confirmation = findChild(app, "clearSavedConfirmation")
    var confirm = findChild(app, "confirmClearSavedButton")
    verify(remove.visible && remove.enabled)
    remove.clicked()
    verify(confirmation.visible)
    compare(confirmation.textFormat, Text.PlainText)
    verify(confirmation.text.indexOf("2") >= 0)
    compare(clearSavedRequests, 0)
    findChild(app, "cancelClearSavedButton").clicked()
    verify(!confirmation.visible)
    compare(clearSavedRequests, 0)
    remove.clicked()
    findChild(app, "settingsNav_themes").clicked()
    verify(!confirmation.visible)
    findChild(app, "settingsNav_saved").clicked()
    verify(!confirmation.visible)
    remove.clicked()
    app.busy = true
    verify(!confirm.enabled)
    app.busy = false
    confirm.clicked()
    compare(clearSavedRequests, 1)
    verify(!confirmation.visible)
    app.model = ({ items: { saved: [] } })
    verify(!remove.enabled)
    compare(findChild(app, "navigationButton_saved").text, app.sectionTitle("saved") + "  0")
  }
}
