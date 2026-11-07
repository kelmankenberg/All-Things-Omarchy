import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "kel.all-things-omarchy"

  property string displayMode: "closed"
  property bool dockedOpen: false
  readonly property bool opened: dockedOpen || window.visible
  property var appData: ({ items: ({ plugins: [], themes: [], videos: [], news: [],
    releases: [], manual: [], hotkeys: [], community: [], events: [], saved: [] }),
    unreadCounts: ({}), newCounts: ({}), errors: ({}), settings: ({}), lastFetched: ({}) })
  property var queries: ({})
  property var filterTerms: ({})
  property var dateRanges: ({})
  property bool navigationCollapsed: false
  property string status: ""
  property bool busy: false
  property bool pendingRefresh: false
  property bool pendingRefreshOnOpen: false
  property bool pendingSystemCheck: false
  property string pendingFilters: ""
  property string resetGroup: ""
  property bool dataLoaded: false
  property string helperAction: ""
  property var displayPreference: ({ mode: "docked", width: 0, height: 0 })
  property bool displayReady: false
  property bool displayWritable: true
  property string displayError: ""
  property string displayAction: ""
  property string pendingDisplayRequest: ""
  property bool pendingDisplaySave: false
  property var systemData: ({})
  property bool systemBusy: false
  property string systemError: ""
  property var themeData: ({})
  property bool themeBusy: false
  property string themeError: ""
  property string themeAction: ""
  property bool updateLaunching: false
  property bool updatePending: false
  property string updateError: ""
  property string updateLog: ""

  readonly property string helperPath: {
    var path = String(Qt.resolvedUrl("Backend.py"))
    if (path.indexOf("file://") === 0) path = path.substring(7)
    try { return decodeURIComponent(path) } catch (e) { return path }
  }

  function runHelper(args) {
    if (helper.running) return false
    helperAction = args[0]
    helper.command = ["python3", helperPath].concat(args)
    helper.running = true
    busy = true
    return true
  }

  function refresh(onOpen) {
    var automatic = onOpen === true
    if (!runHelper(automatic ? ["fetch", "on-open"] : ["fetch"])) {
      pendingRefreshOnOpen = pendingRefresh ? pendingRefreshOnOpen && automatic : automatic
      pendingRefresh = true
      return
    }
    status = ""
  }

  function refreshSystem() {
    if (updateLaunching) return
    updatePending = false
    updateError = ""
    if (!themeHelper.running) {
      themeError = ""
      themeAction = "load"
      themeBusy = true
      themeHelper.command = ["python3", helperPath, "theme-status"]
      themeHelper.running = true
    }
    if (systemHelper.running) return
    systemError = ""
    systemBusy = true
    systemHelper.command = ["python3", helperPath, "system-status"]
    systemHelper.running = true
  }

  function launchUpdate() {
    if (updateLaunching || updatePending || systemBusy || systemError
        || !systemData.update || systemData.update.status !== "available") return
    updateError = ""
    updateLaunching = true
    updateHelper.command = ["python3", helperPath, "launch-update"]
    updateHelper.running = true
  }

  function selectTheme(name) {
    if (themeHelper.running || !name) return
    themeError = ""
    themeAction = "set"
    themeBusy = true
    themeHelper.command = ["python3", helperPath, "theme-set", name]
    themeHelper.running = true
  }

  function loadContent() {
    if (!dataLoaded) {
      if (appData.settings.refreshOnOpen !== false) pendingRefresh = true
      pendingRefreshOnOpen = true
      pendingSystemCheck = true
      runHelper(["load"])
      return
    }
    if (appData.settings.systemCheckOnOpen !== false) refreshSystem()
    if (appData.settings.refreshOnOpen !== false) refresh(true)
  }

  function applyPayload(exitCode, output, errorOutput) {
    busy = false
    try {
      var payload = JSON.parse(String(output || "{}"))
      if (exitCode !== 0 || payload.error) {
        status = payload.error || errorMessage(errorOutput, "Could not update Omarchy sources.")
      } else {
        if (!dataLoaded) restoreFilters(payload.filters || {})
        appData = payload
        dataLoaded = true
        status = ""
        if (pendingSystemCheck) {
          pendingSystemCheck = false
          if (appData.settings.systemCheckOnOpen !== false) refreshSystem()
        }
      }
    } catch (error) {
      status = errorMessage(errorOutput, "The source response could not be read.")
    }
    Qt.callLater(function() { root.flushPendingWork() })
  }

  function loadDisplayPreference() {
    if (displayHelper.running) return
    displayAction = "load"
    displayHelper.command = ["python3", helperPath, "display-load"]
    displayHelper.running = true
  }

  function saveDisplayPreference() {
    if (!displayWritable || !displayReady || displayHelper.running || !pendingDisplaySave) return
    pendingDisplaySave = false
    displayAction = "save"
    displayHelper.command = ["python3", helperPath, "display-save", displayPreference.mode,
      String(displayPreference.width), String(displayPreference.height)]
    displayHelper.running = true
  }

  function queueDisplaySave() {
    pendingDisplaySave = true
    saveDisplayPreference()
  }

  function rememberWindowSize() {
    if (displayMode !== "window" || window.fullscreen
        || window.width < 1 || window.height < 1
        || window.width > 16384 || window.height > 16384) return false
    if (displayPreference.width === window.width && displayPreference.height === window.height) return false
    displayPreference = ({ mode: displayPreference.mode, width: window.width, height: window.height })
    return true
  }

  function setMode(mode, remember) {
    if (["docked", "window", "maximized"].indexOf(mode) === -1) return
    if (!displayReady) {
      pendingDisplayRequest = mode
      loadDisplayPreference()
      return
    }
    sizeSaveTimer.stop()
    rememberWindowSize()
    if (remember !== false) {
      displayPreference = ({ mode: mode, width: displayPreference.width, height: displayPreference.height })
      queueDisplaySave()
    }
    if (mode === "docked") {
      displayMode = "docked"
      window.visible = false
      window.fullscreen = false
      window.maximized = false
      dockedOpen = true
      loadContent()
      return
    }
    dockedOpen = false
    displayMode = mode
    if (mode === "window") {
      window.fullscreen = false
      window.maximized = false
      var maxWidth = window.screen ? Math.max(Style.space(640), window.screen.width - 80) : 16384
      var maxHeight = window.screen ? Math.max(Style.space(440), window.screen.height - 100) : 16384
      var restoredWidth = Math.max(Style.space(640), Math.min(displayPreference.width || 1100, maxWidth))
      var restoredHeight = Math.max(Style.space(440), Math.min(displayPreference.height || 760, maxHeight))
      window.implicitWidth = restoredWidth
      window.implicitHeight = restoredHeight
    }
    window.visible = true
    if (mode === "maximized") window.fullscreen = true
    else sizeSaveTimer.restart()
    loadContent()
  }

  function openDocked() {
    setMode("docked")
  }

  function open() {
    if (!displayReady) {
      pendingDisplayRequest = "restore"
      loadDisplayPreference()
      return
    }
    setMode(displayPreference.mode, false)
  }

  function close() {
    sizeSaveTimer.stop()
    if (rememberWindowSize()) queueDisplaySave()
    window.visible = false
    closePanel()
  }

  function closePanel() {
    filterSaveTimer.stop()
    flushPendingWork()
    pendingDisplayRequest = ""
    dockedOpen = false
    displayMode = "closed"
  }

  function mutate(args) {
    if (!runHelper(args)) {
      status = "Please wait for the current update to finish."
      return false
    }
    return true
  }

  function updateQuery(section, value) {
    var next = ({})
    for (var key in queries) next[key] = queries[key]
    next[section] = value
    queries = next
    queueFilters()
  }

  function updateFilterTerms(section, value) {
    var next = ({})
    for (var key in filterTerms) next[key] = filterTerms[key]
    next[section] = value
    filterTerms = next
    queueFilters()
  }

  function updateDateRange(section, value) {
    var next = ({})
    for (var key in dateRanges) next[key] = dateRanges[key]
    next[section] = value
    dateRanges = next
    queueFilters()
  }

  function restoreFilters(filters) {
    var nextQueries = ({})
    var nextTerms = ({})
    var nextRanges = ({})
    for (var section in filters) {
      nextQueries[section] = filters[section].query
      nextTerms[section] = filters[section].terms
      nextRanges[section] = filters[section].range
    }
    queries = nextQueries
    filterTerms = nextTerms
    dateRanges = nextRanges
  }

  function queueFilters() {
    if (!dataLoaded) return
    var filters = ({})
    var sections = ["plugins", "themes", "videos", "news", "releases", "manual", "hotkeys",
      "community", "events", "saved"]
    sections.forEach(function(section) {
      if (root.appData.settings["remember_" + section] === false) return
      filters[section] = { query: root.queries[section] || "", terms: root.filterTerms[section] || [],
        range: root.dateRanges[section] || "all" }
    })
    var serialized = JSON.stringify(filters)
    if (encodeURIComponent(serialized).replace(/%[A-F0-9]{2}/g, "x").length > 65536) {
      filterSaveTimer.stop()
      pendingFilters = ""
      status = strings.t("settings.filtersTooLarge")
      return
    }
    pendingFilters = serialized
    filterSaveTimer.restart()
  }

  function flushPendingWork() {
    if (helper.running) return
    if (pendingFilters && !filterSaveTimer.running) {
      var filters = pendingFilters
      pendingFilters = ""
      runHelper(["save-filters", filters])
      return
    }
    if (pendingRefresh) {
      var automatic = pendingRefreshOnOpen
      pendingRefresh = false
      pendingRefreshOnOpen = false
      refresh(automatic)
    }
  }

  function resetSettings(group) {
    if (!mutate(["reset-settings", group])) return
    filterSaveTimer.stop()
    pendingFilters = ""
    resetGroup = group
  }

  Timer {
    id: filterSaveTimer
    interval: 500
    onTriggered: root.flushPendingWork()
  }

  function updateDataSetting(key, value) {
    if (!mutate(["set-setting", key, String(value)])) return
  }

  function errorMessage(output, fallback) {
    try {
      var payload = JSON.parse(String(output || "{}"))
      if (payload.error) return String(payload.error).slice(0, 240)
    } catch (ignored) {}
    return String(output || fallback).slice(0, 240)
  }

  function applyDataMutation(exitCode, output, errorOutput) {
    try {
      var payload = JSON.parse(String(output || "{}"))
      if (exitCode !== 0 || payload.error) status = payload.error
        || errorMessage(errorOutput, "Could not save the change.")
      else {
        appData = payload
        dataLoaded = true
        status = ""
        if (resetGroup) {
          var queriesCopy = Object.assign({}, queries)
          var termsCopy = Object.assign({}, filterTerms)
          var rangesCopy = Object.assign({}, dateRanges)
          delete queriesCopy[resetGroup]
          delete termsCopy[resetGroup]
          delete rangesCopy[resetGroup]
          queries = queriesCopy
          filterTerms = termsCopy
          dateRanges = rangesCopy
          queueFilters()
        }
        if (root.helperAction === "set-setting") queueFilters()
      }
    } catch (error) {
      status = errorMessage(errorOutput, "Could not read the saved change.")
    }
    busy = false
    resetGroup = ""
    Qt.callLater(function() { root.flushPendingWork() })
  }

  Process {
    id: helper
    stdout: StdioCollector { id: helperOut; waitForEnd: true }
    stderr: StdioCollector { id: helperErr; waitForEnd: true }
    onExited: function(exitCode) {
      var output = String(helperOut.text || "")
      var errorOutput = String(helperErr.text || "")
      if (["fetch", "load"].indexOf(root.helperAction) >= 0) root.applyPayload(exitCode, output, errorOutput)
      else root.applyDataMutation(exitCode, output, errorOutput)
    }
  }

  Process {
    id: updateHelper
    stdout: StdioCollector { id: updateOut; waitForEnd: true }
    stderr: StdioCollector { id: updateErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.updateLaunching = false
      try {
        if (exitCode !== 0) throw new Error(root.errorMessage(updateErr.text, "Could not launch the update terminal."))
        var result = JSON.parse(String(updateOut.text || ""))
        if (result.requested !== true || typeof result.log !== "string" || !result.log)
          throw new Error("The update launch response is invalid.")
        root.updateLog = result.log
        root.updatePending = true
      } catch (error) {
        root.updateError = String(error.message || error).slice(0, 240)
      }
    }
  }

  Process {
    id: themeHelper
    stdout: StdioCollector { id: themeOut; waitForEnd: true }
    stderr: StdioCollector { id: themeErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.themeBusy = false
      try {
        if (exitCode !== 0) throw new Error(root.errorMessage(themeErr.text, "Could not update the theme."))
        var result = JSON.parse(String(themeOut.text || ""))
        if (!result.current || !Array.isArray(result.themes))
          throw new Error("The theme response is invalid.")
        root.themeData = result
      } catch (error) {
        root.themeError = String(error.message || error).slice(0, 240)
      }
    }
  }

  Process {
    id: systemHelper
    stdout: StdioCollector { id: systemOut; waitForEnd: true }
    stderr: StdioCollector { id: systemErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.systemBusy = false
      try {
        if (exitCode !== 0) throw new Error(root.errorMessage(systemErr.text, "Could not check system status."))
        var result = JSON.parse(String(systemOut.text || ""))
        if (!result.version || !result.theme || !result.update)
          throw new Error("The system status response is invalid.")
        root.systemData = result
      } catch (error) {
        root.systemError = String(error.message || error).slice(0, 240)
      }
    }
  }

  Process {
    id: displayHelper
    stdout: StdioCollector { id: displayOut; waitForEnd: true }
    stderr: StdioCollector { id: displayErr; waitForEnd: true }
    onExited: function(exitCode) {
      if (root.displayAction === "load") {
        try {
          if (exitCode !== 0) throw new Error(root.errorMessage(displayErr.text, "Could not load the display preference."))
          var preference = JSON.parse(String(displayOut.text || ""))
          if (["docked", "window", "maximized"].indexOf(preference.mode) < 0
              || !Number.isInteger(preference.width) || !Number.isInteger(preference.height)
              || preference.width < 0 || preference.height < 0
              || preference.width > 16384 || preference.height > 16384
              || (preference.width === 0) !== (preference.height === 0))
            throw new Error("The saved display preference is invalid.")
          root.displayPreference = preference
        } catch (error) {
          root.displayWritable = false
          root.displayError = String(error.message || error)
        }
        root.displayReady = true
        var request = root.pendingDisplayRequest
        root.pendingDisplayRequest = ""
        if (request) {
          if (request === "restore") root.open()
          else root.setMode(request)
        }
      } else if (exitCode !== 0) {
        root.displayError = root.errorMessage(displayErr.text, "Could not save the display preference.")
      } else {
        root.displayError = ""
      }
      if (root.pendingDisplaySave) Qt.callLater(function() { root.saveDisplayPreference() })
    }
  }

  Timer {
    id: sizeSaveTimer
    interval: 400
    repeat: false
    onTriggered: { if (root.rememberWindowSize()) root.queueDisplaySave() }
  }

  ShellIpc {
    target: "kel.all-things-omarchy"
    function setMode(mode: string) { root.setMode(mode) }
    function status(): string {
      return JSON.stringify({ mode: root.displayMode, docked: root.dockedOpen,
        visible: window.visible, fullscreen: window.fullscreen })
    }
  }

  Commons.Translations {
    id: strings
    directory: Qt.resolvedUrl("i18n")
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: barSize

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "A"
    fontSize: Style.font.body
    tooltipText: strings.t("widget.tooltip")
    onPressed: {
      if (root.pendingDisplayRequest) root.pendingDisplayRequest = ""
      else if (window.visible) root.close()
      else if (root.dockedOpen) root.closePanel()
      else root.open()
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.dockedOpen
    focusTarget: dockedView
    contentWidth: popup.fittedContentWidth(Style.space(760), 900)
    contentHeight: popup.fittedContentHeight(dockedView.implicitHeight, 820)

    AppContent {
      id: dockedView
      anchors.fill: parent
      translations: strings
      model: root.appData
      status: root.displayError || root.status
      busy: root.busy
      queries: root.queries
      filterTerms: root.filterTerms
      dateRanges: root.dateRanges
      navigationCollapsed: root.navigationCollapsed
      systemData: root.systemData
      systemBusy: root.systemBusy
      systemError: root.systemError
      themeData: root.themeData
      themeBusy: root.themeBusy
      themeAction: root.themeAction
      themeError: root.themeError
      updateLaunching: root.updateLaunching
      updatePending: root.updatePending
      updateError: root.updateError
      updateLog: root.updateLog
      displayMode: root.displayMode
      onRefreshRequested: root.refresh()
      onModeRequested: function(mode) { root.setMode(mode) }
      onQueryChanged: function(section, value) { root.updateQuery(section, value) }
      onFilterTermsEdited: function(section, value) { root.updateFilterTerms(section, value) }
      onDateRangeChanged: function(section, value) { root.updateDateRange(section, value) }
      onMutationRequested: function(action, itemId) { root.mutate([action, itemId]) }
      onSettingChanged: function(key, value) { root.updateDataSetting(key, value) }
      onSettingsResetRequested: function(group) { root.resetSettings(group) }
      onClearSavedRequested: root.mutate(["clear-saved"])
      onCloseRequested: root.closePanel()
      onNavigationToggleRequested: root.navigationCollapsed = !root.navigationCollapsed
      onSystemRequested: root.refreshSystem()
      onThemeSelected: function(name) { root.selectTheme(name) }
      onUpdateRequested: root.launchUpdate()
      onOpenUrlRequested: function(url) { Qt.openUrlExternally(url) }
    }
  }

  FloatingWindow {
    id: window
    visible: false
    title: strings.t("window.title")
    color: Commons.Color.popups.background
    implicitWidth: 1100
    implicitHeight: 760
    minimumSize: Qt.size(Style.space(640), Style.space(440))

    AppContent {
      anchors.fill: parent
      translations: strings
      model: root.appData
      status: root.displayError || root.status
      busy: root.busy
      queries: root.queries
      filterTerms: root.filterTerms
      dateRanges: root.dateRanges
      navigationCollapsed: root.navigationCollapsed
      systemData: root.systemData
      systemBusy: root.systemBusy
      systemError: root.systemError
      themeData: root.themeData
      themeBusy: root.themeBusy
      themeAction: root.themeAction
      themeError: root.themeError
      updateLaunching: root.updateLaunching
      updatePending: root.updatePending
      updateError: root.updateError
      updateLog: root.updateLog
      windowMode: true
      displayMode: root.displayMode
      onRefreshRequested: root.refresh()
      onModeRequested: function(mode) { root.setMode(mode) }
      onQueryChanged: function(section, value) { root.updateQuery(section, value) }
      onFilterTermsEdited: function(section, value) { root.updateFilterTerms(section, value) }
      onDateRangeChanged: function(section, value) { root.updateDateRange(section, value) }
      onMutationRequested: function(action, itemId) { root.mutate([action, itemId]) }
      onSettingChanged: function(key, value) { root.updateDataSetting(key, value) }
      onSettingsResetRequested: function(group) { root.resetSettings(group) }
      onClearSavedRequested: root.mutate(["clear-saved"])
      onCloseRequested: root.close()
      onNavigationToggleRequested: root.navigationCollapsed = !root.navigationCollapsed
      onSystemRequested: root.refreshSystem()
      onThemeSelected: function(name) { root.selectTheme(name) }
      onUpdateRequested: root.launchUpdate()
      onOpenUrlRequested: function(url) { Qt.openUrlExternally(url) }
    }

    onVisibleChanged: {
      if (!visible && root.displayMode !== "docked") {
        sizeSaveTimer.stop()
        if (root.rememberWindowSize()) root.queueDisplaySave()
        root.displayMode = "closed"
      }
    }
    onWidthChanged: {
      if (visible && root.displayMode === "window" && !fullscreen) sizeSaveTimer.restart()
    }
    onHeightChanged: {
      if (visible && root.displayMode === "window" && !fullscreen) sizeSaveTimer.restart()
    }
  }
}
