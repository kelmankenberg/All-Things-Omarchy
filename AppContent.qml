import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import "Feed.js" as Feed

Rectangle {
  id: root
  color: Commons.Color.popups.background
  implicitWidth: Style.space(760)
  implicitHeight: Style.space(660)
  clip: true

  property var translations
  property var model: ({})
  property string status: ""
  property bool busy: false
  property var queries: ({})
  property var filterTerms: ({})
  property var dateRanges: ({})
  property var hideReadBySection: ({})
  property double currentTime: Date.now()
  property bool windowMode: false
  property bool navigationCollapsed: false
  readonly property int navigationMinWidth: 140
  readonly property int navigationMaxWidth: 360
  readonly property int navigationDefaultWidth: 160
  property int navigationWidth: navigationDefaultWidth
  readonly property int savedNavigationWidth: Math.max(navigationMinWidth, Math.min(navigationMaxWidth,
    Number(setting("navigationWidth", navigationDefaultWidth))))
  readonly property int navigationLimit: Math.max(navigationMinWidth, Math.min(navigationMaxWidth,
    Math.floor(width * 0.45 / (Style.space(1000) / 1000))))
  readonly property int effectiveNavigationWidth: width > 0
    ? Math.min(navigationWidth, navigationLimit) : navigationWidth
  onSavedNavigationWidthChanged: navigationWidth = savedNavigationWidth
  Component.onCompleted: navigationWidth = savedNavigationWidth
  property var systemData: ({})
  property bool systemBusy: false
  property string systemError: ""
  property var themeData: ({})
  property bool themeBusy: false
  property string themeAction: ""
  property string themeError: ""
  property bool updateLaunching: false
  property bool updatePending: false
  property string updateError: ""
  property string updateLog: ""
  property string filterNotice: ""
  property var thumbnailSources: ({})
  property bool readingActive: true
  readonly property var bulkItems: currentSection === "dashboard" ? allLoadedItems()
    : ((model.items || {})[currentSection] || [])

  signal refreshRequested()
  signal modeRequested(string mode)
  signal queryChanged(string section, string value)
  signal filterTermsEdited(string section, var value)
  signal dateRangeChanged(string section, string value)
  signal hideReadChanged(string section, bool value)
  signal mutationRequested(string action, string itemId)
  signal settingChanged(string key, string value)
  signal settingsResetRequested(string group)
  signal clearSavedRequested()
  signal closeRequested()
  signal navigationToggleRequested()
  signal systemRequested()
  signal themeSelected(string name)
  signal updateRequested()
  signal openUrlRequested(string url)
  signal thumbnailRequested(string url)
  signal thumbnailFailed()

  property string currentSection: "dashboard"
  property string currentSettingsSection: "general"
  property string displayMode: windowMode ? "window" : "docked"
  readonly property var optionalSectionIds: ["plugins", "themes", "videos", "news",
    "releases", "manual", "hotkeys", "community", "events", "system"]
  readonly property var sectionIds: ["dashboard"].concat(optionalSectionIds.filter(function(section) {
    return root.sectionEnabled(section)
  }), ["saved", "settings"])
  readonly property var rangeIds: ["all", "today", "week", "month"]
  readonly property var briefingSources: ["plugins", "themes", "videos", "news", "releases", "community"]
  readonly property var sourceIds: briefingSources.concat(["events", "manual", "hotkeys"])
  readonly property var visibleSourceIds: sourceIds.filter(function(section) {
    return root.sectionEnabled(section)
  })
  readonly property var visibleBriefingSources: briefingSources.filter(function(section) {
    return root.sectionEnabled(section)
  })
  readonly property var settingsSections: ["general", "sections", "refresh", "dashboard"]
    .concat(visibleSourceIds, ["saved", "help"])
  readonly property string pluginVersion: String(model.pluginVersion || "")
  readonly property bool compactRows: setting("density", "comfortable") === "compact"
  readonly property bool showPreviews: setting("showPreviews", true)
  readonly property var dashboardOrder: String(setting("dashboardOrder", "system,sources,events,saved")).split(",")
  readonly property var visibleDashboardPanels: dashboardOrder.filter(function(panel) {
    return (panel !== "system" || root.sectionEnabled("system"))
      && (panel !== "events" || root.sectionEnabled("events"))
  })
  readonly property var upcomingItems: dashboardItems("events")
  readonly property var readingQueue: dashboardItems("saved")
  readonly property var sourceIssues: visibleSourceIds.filter(function(section) {
    return !!(root.model.errors || {})[section]
  })
  readonly property var dashboardTileSources: visibleBriefingSources.concat(sourceIssues.filter(function(section) {
    return root.visibleBriefingSources.indexOf(section) < 0
  }))
  readonly property var sectionIcons: ({
    dashboard: "\uf00a", plugins: "\uf12e", themes: "\uf1fc",
    videos: "\uf16a", news: "\uf1ea", releases: "\uf135", manual: "\uf02d",
    hotkeys: "\uf11c", community: "\uf0c0", events: "\uf073", system: "\uf108",
    saved: "\uf02e", settings: "\uf013"
  })

  component OutlineButton: Button {
    id: control
    property bool iconOnly: false
    property bool bordered: !iconOnly
    property string leadingIcon: ""
    property string description: ""
    Accessible.name: description || text
    ToolTip.visible: description !== "" && hovered
    ToolTip.delay: 400
    ToolTip.text: description
    contentItem: Text {
      text: control.leadingIcon ? control.leadingIcon + "  " + control.text : control.text
      textFormat: Text.PlainText
      color: control.highlighted || (control.iconOnly && (control.activeFocus || control.hovered))
        ? Commons.Color.accent : Commons.Color.popups.text
      opacity: control.enabled ? 1 : 0.5
      font.family: Style.font.family
      font.pixelSize: control.iconOnly ? Style.font.icon : Style.font.body
      horizontalAlignment: control.leadingIcon ? Text.AlignLeft : Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
      elide: Text.ElideRight
    }
    background: Rectangle {
      implicitWidth: Style.space(control.iconOnly ? 32 : 60)
      implicitHeight: Style.space(32)
      radius: Style.cornerRadius
      color: "transparent"
      border.width: control.bordered ? (control.activeFocus || control.highlighted ? 2 : 1) : 0
      border.color: control.activeFocus || control.highlighted || control.hovered
        ? Commons.Color.accent : Commons.Color.popups.border
      opacity: control.enabled ? 1 : 0.5
    }
  }

  readonly property real scrollGutter: Style.space(14)

  component ThemedScrollBar: ScrollBar {
    id: bar
    readonly property bool needed: size < 0.999
    policy: needed ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
    hoverEnabled: true
    minimumSize: 0.08
    padding: Style.space(2)
    contentItem: Rectangle {
      implicitWidth: Style.space(6)
      implicitHeight: Style.space(32)
      radius: width / 2
      color: bar.pressed || bar.hovered ? Commons.Color.accent : Commons.Color.popups.text
      opacity: bar.pressed ? 0.95 : bar.hovered ? 0.75 : 0.4
    }
    background: Rectangle {
      implicitWidth: Style.space(10)
      radius: width / 2
      color: "transparent"
      border.width: 1
      border.color: Commons.Color.popups.border
      opacity: bar.hovered || bar.pressed ? 0.9 : 0.5
    }
  }

  component ViewScrollBar: ThemedScrollBar {
    required property Item view
    parent: view
    x: view.mirrored ? 0 : view.width - width
    y: view.topPadding
    height: view.availableHeight
  }

  component HoverButton: OutlineButton {
    id: hoverButton
    bordered: false
    hoverEnabled: true
    background: Rectangle {
      implicitWidth: Style.space(60)
      implicitHeight: Style.space(32)
      radius: Style.cornerRadius
      border.width: 0
      color: hoverButton.visualFocus ? Style.focusFillFor(Commons.Color.popups.text, Commons.Color.accent)
        : hoverButton.hovered ? Style.hoverFillFor(Commons.Color.popups.text, Commons.Color.accent)
        : "transparent"
    }
  }

  component BriefingText: Text {
    Layout.fillWidth: true
    textFormat: Text.PlainText
    color: Commons.Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    wrapMode: Text.Wrap
  }

  component TogglePreference: RowLayout {
    id: preference
    required property string settingKey
    required property string label
    property bool defaultValue: true
    Layout.fillWidth: true
    BriefingText { text: preference.label }
    CheckBox {
      objectName: "setting_" + preference.settingKey
      Accessible.name: preference.label
      enabled: !root.busy
      checked: root.setting(preference.settingKey, preference.defaultValue)
      onToggled: root.settingChanged(preference.settingKey, checked ? "true" : "false")
    }
  }

  component ChoicePreference: RowLayout {
    id: preference
    required property string settingKey
    required property string label
    required property var values
    property var labels: values.map(function(value) { return String(value) })
    property var defaultValue: values[0]
    Layout.fillWidth: true
    BriefingText { text: preference.label }
    ComboBox {
      id: preferenceCombo
      objectName: "setting_" + preference.settingKey
      Accessible.name: preference.label
      Layout.preferredWidth: Style.space(150)
      enabled: !root.busy
      model: preference.labels
      currentIndex: preference.values.indexOf(root.setting(preference.settingKey, preference.defaultValue))
      onActivated: function(index) { root.settingChanged(preference.settingKey, String(preference.values[index])) }
      contentItem: Text {
        text: preferenceCombo.displayText
        textFormat: Text.PlainText
        color: Commons.Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        rightPadding: preferenceCombo.indicator ? preferenceCombo.indicator.width + Style.space(8) : 0
      }
    }
  }

  component BriefingPanel: Rectangle {
    id: briefingPanel
    property string title: ""
    property string actionText: ""
    property string actionObjectName: ""
    property bool actionEnabled: true
    signal actionClicked()
    default property alias contents: panelContents.data
    Layout.fillWidth: true
    implicitHeight: panelContents.implicitHeight + Style.space(20)
    color: "transparent"
    border.color: Commons.Color.popups.border
    border.width: 1
    radius: Style.cornerRadius
    ColumnLayout {
      id: panelContents
      anchors.fill: parent
      anchors.margins: Style.space(10)
      spacing: Style.space(6)
      RowLayout {
        visible: briefingPanel.title !== "" || briefingPanel.actionText !== ""
        Layout.fillWidth: true
        BriefingText {
          text: briefingPanel.title
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
          wrapMode: Text.NoWrap
        }
        HoverButton {
          objectName: briefingPanel.actionObjectName
          visible: briefingPanel.actionText !== ""
          implicitHeight: Style.space(26)
          text: briefingPanel.actionText
          enabled: briefingPanel.actionEnabled
          onClicked: briefingPanel.actionClicked()
        }
      }
    }
  }

  component DashboardLink: HoverButton {
    required property var item
    property string tooltipText: ""
    objectName: "dashboardLink_" + item.id
    Layout.fillWidth: true
    implicitHeight: Style.space(28)
    leftPadding: Style.space(6)
    rightPadding: Style.space(6)
    enabled: !root.busy
    onClicked: root.openItem(item)
    PlainToolTip {
      objectName: "dashboardLinkTooltip"
      visible: parent.hovered && parent.tooltipText !== ""
      text: parent.tooltipText
    }
  }

  component PlainToolTip: ToolTip {
    id: tip
    delay: 400
    contentItem: Text {
      text: tip.text
      textFormat: Text.PlainText
      font: tip.font
      wrapMode: Text.Wrap
      color: tip.palette.toolTipText
    }
  }

  component SourceTile: Button {
    id: tile
    property string section: ""
    readonly property string error: String((root.model.errors || {})[section] || "")
    readonly property int newItems: root.count(section, "new")
    readonly property int unreadItems: root.count(section, "unread")
    readonly property string detail: error ? root.t("dashboard.sourceFailed")
      : root.isReference(section) ? root.t("dashboard.reference").arg(Commons.I18n.formatNumber(
        ((root.model.items || {})[section] || []).length))
      : newItems + unreadItems === 0 ? root.t("dashboard.allRead")
      : newItems === 0 ? root.t("dashboard.unread").arg(Commons.I18n.formatNumber(unreadItems))
      : root.t("dashboard.counts").arg(Commons.I18n.formatNumber(newItems)).arg(Commons.I18n.formatNumber(unreadItems))
    objectName: "dashboardTile_" + section
    Layout.fillWidth: true
    hoverEnabled: true
    padding: Style.space(8)
    Accessible.name: root.sectionTitle(section) + ", " + detail
    onClicked: root.setSection(section)
    PlainToolTip {
      objectName: "dashboardSourceTooltip"
      visible: tile.hovered
      text: tile.error || root.sourceRefreshTime(tile.section)
    }
    contentItem: ColumnLayout {
      spacing: Style.space(2)
      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: (root.sectionIcons[tile.section] || "") + "  " + root.sectionTitle(tile.section)
        color: tile.newItems > 0 ? Commons.Color.accent : Commons.Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
      Text {
        objectName: "dashboardTileDetail_" + tile.section
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: tile.detail
        color: tile.error ? Commons.Color.urgent : Commons.Color.popups.text
        opacity: tile.error ? 1 : 0.7
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideRight
      }
    }
    background: Rectangle {
      radius: Style.cornerRadius
      color: tile.visualFocus ? Style.focusFillFor(Commons.Color.popups.text, Commons.Color.accent)
        : tile.hovered ? Style.hoverFillFor(Commons.Color.popups.text, Commons.Color.accent) : "transparent"
      border.width: tile.visualFocus ? 2 : 1
      border.color: tile.error ? Commons.Color.urgent
        : tile.newItems > 0 || tile.hovered ? Commons.Color.accent : Commons.Color.popups.border
    }
  }

  component ThemeThumbnail: Rectangle {
    property string imageUrl: ""
    implicitWidth: Style.space(64)
    implicitHeight: Style.space(40)
    color: "transparent"
    border.width: 0
    clip: true

    Image {
      id: themeImage
      objectName: "thumbnailImage"
      anchors.fill: parent
      source: parent.imageUrl.indexOf("file:///") === 0 ? parent.imageUrl : ""
      sourceSize.width: 128
      sourceSize.height: 80
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      visible: status === Image.Ready
      onStatusChanged: if (status === Image.Error) root.thumbnailFailed()
    }
    Text {
      objectName: "thumbnailFallback"
      anchors.centerIn: parent
      visible: themeImage.status !== Image.Ready
      text: "\uf03e"
      textFormat: Text.PlainText
      color: Commons.Color.popups.text
      opacity: 0.5
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }
  }

  function t(key) {
    return translations ? translations.t(key) : key
  }

  function setting(key, fallback) {
    var settings = root.model.settings || {}
    return settings[key] === undefined ? fallback : settings[key]
  }

  function sectionEnabled(section) {
    return optionalSectionIds.indexOf(section) < 0 || setting("section_" + section, true) !== false
  }

  function itemBorderColor(item) {
    return item.isRead === true ? Commons.Color.muted : Commons.Color.popups.border
  }

  function settingsSectionTitle(section) {
    return section === "general" ? t("settings.appearance")
      : section === "sections" ? t("settings.sections")
      : section === "help" ? t("settings.help")
      : section === "refresh" ? t("settings.refresh") : sectionTitle(section)
  }

  function reportIssue(template) {
    if (!pluginVersion || ["bug_report.yml", "feature_request.yml"].indexOf(template) < 0) return
    openUrlRequested("https://github.com/kelmankenberg/All-Things-Omarchy/issues/new?template="
      + template + "&plugin_version=" + encodeURIComponent(pluginVersion))
  }

  function dashboardPanelTitle(panel) {
    return t(({ system: "dashboard.systemTitle", sources: "dashboard.sources",
      events: "dashboard.upcoming", saved: "dashboard.readingQueue" })[panel])
  }

  function moveDashboardPanel(panel, offset) {
    var order = dashboardOrder.slice()
    var visiblePanels = visibleDashboardPanels
    var index = visiblePanels.indexOf(panel)
    var other = index + offset
    if (index < 0 || other < 0 || other >= visiblePanels.length) return
    var orderIndex = order.indexOf(panel)
    var otherOrderIndex = order.indexOf(visiblePanels[other])
    order[orderIndex] = order[otherOrderIndex]
    order[otherOrderIndex] = panel
    settingChanged("dashboardOrder", order.join(","))
  }

  function sectionItems(section) {
    if (!sectionEnabled(section)) return []
    var items = model.items ? model.items[section] : []
    var undated = section === "themes" || section === "community" || isReference(section)
    var ordered = undated || section === "events"
    var terms = (filterTerms[section] || []).slice()
    terms.push(queries[section] || "")
    var rows = Feed.filterItems(items, section === "saved" || undated
      ? "all" : (dateRanges[section] || "all"), terms, currentTime, !ordered, section === "events")
    if (hideReadBySection[section] === true)
      rows = rows.filter(function(item) { return item.isRead !== true })
    if (section === "events") rows.sort(function(a, b) {
      var now = root.currentTime / 1000
      var upcomingA = Number(a.timestamp) >= now
      var upcomingB = Number(b.timestamp) >= now
      return upcomingA !== upcomingB ? (upcomingA ? -1 : 1)
        : upcomingA ? Number(a.timestamp) - Number(b.timestamp)
        : Number(b.timestamp) - Number(a.timestamp)
    })
    return rows
  }

  function allLoadedItems() {
    var rows = []
    visibleSourceIds.concat(["saved"]).forEach(function(section) {
      rows = rows.concat((root.model.items || {})[section] || [])
    })
    return rows
  }

  component ReadingTracker: ScrollReadTracker {
    id: tracker
    tracking: root.readingActive && root.visible && root.setting("markReadOnScroll", true)
    busy: root.busy
    contextKey: JSON.stringify([root.currentSection, root.queries, root.filterTerms, root.dateRanges,
      root.hideReadBySection])
    onReadRequested: function(ids) { root.mutationRequested("mark-read-items", JSON.stringify(ids)) }
    Connections {
      target: root
      function onMutationRequested(action, itemId) {
        if (action !== "mark-read-items") tracker.resetReading()
      }
    }
  }

  function addFilterTerm(section) {
    var value = String(queries[section] || "").trim()
    if (!value) return
    if ((filterTerms[section] || []).length >= 16) {
      filterNotice = t("settings.filterLimit")
      return
    }
    filterNotice = ""
    filterTermsEdited(section, Feed.addTerm(filterTerms[section], value))
    queryChanged(section, "")
  }

  function removeFilterTerm(section, index) {
    var terms = (filterTerms[section] || []).slice()
    terms.splice(index, 1)
    filterNotice = ""
    filterTermsEdited(section, terms)
  }

  function isReference(section) {
    return section === "manual" || section === "hotkeys"
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    onTriggered: root.currentTime = Date.now()
  }

  function count(section, type) {
    if (type === "saved") return model.items && model.items.saved ? model.items.saved.length : 0
    var counts = model[type + "Counts"] || {}
    return Number(counts[section] || 0)
  }

  function newCount(section) {
    if (section === "dashboard") return visibleSourceIds.reduce(function(total, source) {
      return total + count(source, "new")
    }, 0)
    if (section === "saved") return (model.items && model.items.saved || []).filter(function(item) {
      return item.isNew === true
    }).length
    if (section === "system") return 0
    return sourceIds.indexOf(section) >= 0 ? count(section, "new") : 0
  }

  function plural(key, count) {
    var formatted = Commons.I18n.formatNumber(count)
    return translations ? translations.tn(key, count).arg(formatted) : t(key).arg(formatted)
  }

  function dashboardItems(group) {
    var items = root.model.items || {}
    if (group === "events") return sectionEnabled("events") ? (items.events || []).filter(function(item) {
      return Number(item.timestamp) > root.currentTime / 1000
    }).slice().sort(function(a, b) { return Number(a.timestamp) - Number(b.timestamp) }) : []
    if (group === "saved") return (items.saved || []).filter(function(item) {
      return !item.isRead
    })
    return []
  }

  function eventCountdown(item) {
    var hours = Math.max(1, Math.ceil((Number(item.timestamp) * 1000 - currentTime) / 3600000))
    return hours < 24 ? t("dashboard.inHours").arg(Qt.locale(Commons.I18n.formatLocale).toString(hours, "f", 0))
      : t("dashboard.inDays").arg(Qt.locale(Commons.I18n.formatLocale).toString(Math.ceil(hours / 24), "f", 0))
  }

  function eventDescription(item) {
    return [item.name, new Date(item.timestamp * 1000).toLocaleString(Qt.locale(Commons.I18n.formatLocale), Locale.ShortFormat),
      eventCountdown(item), item.author].filter(function(value) { return !!value }).join(" · ")
  }

  function sourceRefreshTime(section) {
    var timestamp = Number((root.model.lastFetched || {})[section] || 0)
    return timestamp > 0 ? t("dashboard.refreshed").arg(
      new Date(timestamp * 1000).toLocaleString(Qt.locale(Commons.I18n.formatLocale), Locale.ShortFormat))
      : t("dashboard.notRefreshed")
  }

  function setSection(section) {
    if (sectionIds.indexOf(section) < 0) {
      if (optionalSectionIds.indexOf(section) >= 0) currentSection = "dashboard"
      return
    }
    var changed = currentSection !== section
    currentSection = section
    filterNotice = ""
    if (changed && (section === "system" || section === "dashboard")
        && sectionEnabled("system") && setting("systemCheckOnOpen", true)) systemRequested()
  }

  onSectionIdsChanged: {
    if (sectionIds.indexOf(currentSection) < 0) currentSection = "dashboard"
  }
  onSettingsSectionsChanged: {
    if (settingsSections.indexOf(currentSettingsSection) < 0)
      currentSettingsSection = "sections"
  }

  function openItem(item) {
    if (!item || typeof item.url !== "string" || item.url.indexOf("https://") !== 0) return
    if (!isReference(item.kind) && setting("markReadOnOpen", true)) mutationRequested("mark-read", item.id)
    openUrlRequested(item.url)
  }

  function sectionTitle(section) {
    return t("nav." + section)
  }

  function sectionSource(section) {
    return ({
      plugins: "https://plugins.omarchy.org/",
      themes: "https://omarchy.org/themes/",
      videos: "https://www.youtube.com/results?search_query=Omarchy",
      news: "https://omarchy.org/news/",
      releases: "https://github.com/omacom/omarchy/releases",
      manual: "https://omarchy.org/manual/",
      hotkeys: "https://omarchy.org/manual/hotkeys/",
      community: "https://omarchy.deepakness.com/resources",
      events: "https://omarchy.org/meetups/"
    })[section] || ""
  }

  ColumnLayout {
    anchors.fill: parent
    spacing: 0

    Rectangle {
      objectName: "topToolbar"
      Layout.fillWidth: true
      Layout.preferredHeight: Style.space(52)
      color: Commons.Color.popups.background

      Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Commons.Color.popups.border
      }

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(10)
        anchors.rightMargin: Style.space(12)
        spacing: Style.space(6)

        OutlineButton {
          objectName: "navigationToggleButton"
          iconOnly: true
          text: "\uf0c9"
          description: root.navigationCollapsed ? root.t("nav.expand") : root.t("nav.collapse")
          onClicked: root.navigationToggleRequested()
        }
        Text {
          objectName: "toolbarTitle"
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.t("brand")
          color: Commons.Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.title
          font.bold: true
          elide: Text.ElideRight
        }
        OutlineButton {
          objectName: "toolbarRefreshButton"
          visible: root.currentSection !== "settings"
            && (root.visibleSourceIds.length > 0 || root.sectionEnabled("system"))
          enabled: root.currentSection === "system"
            ? !root.systemBusy && !root.themeBusy && !root.updateLaunching : !root.busy
          iconOnly: true
          text: "\uf021"
          description: (root.currentSection === "system"
            ? root.systemBusy || root.themeBusy || root.updateLaunching : root.busy)
            ? root.t("actions.loading") : root.t("actions.refresh")
          onClicked: {
            if (root.currentSection === "system") root.systemRequested()
            else {
              root.refreshRequested()
              if (root.currentSection === "dashboard" && root.sectionEnabled("system"))
                root.systemRequested()
            }
          }
        }
        OutlineButton {
          iconOnly: true
          text: "\uf2d0"
          description: root.t("mode.docked")
          highlighted: root.displayMode === "docked"
          onClicked: root.modeRequested("docked")
        }
        OutlineButton {
          iconOnly: true
          text: "\uf2d2"
          description: root.t("mode.window")
          highlighted: root.displayMode === "window"
          onClicked: root.modeRequested("window")
        }
        OutlineButton {
          iconOnly: true
          text: "\uf065"
          description: root.t("mode.maximized")
          highlighted: root.displayMode === "maximized"
          onClicked: root.modeRequested("maximized")
        }
        OutlineButton {
          visible: root.windowMode
          text: root.t("actions.close")
          onClicked: root.closeRequested()
        }
      }
    }

    RowLayout {
      Layout.fillWidth: true
      Layout.fillHeight: true
      spacing: 0

      Rectangle {
        id: navigationPanel
        objectName: "navigationPanel"
        Layout.preferredWidth: Style.space(root.navigationCollapsed ? 52 : root.effectiveNavigationWidth)
        Layout.minimumWidth: Layout.preferredWidth
        Layout.maximumWidth: Layout.preferredWidth
        Layout.fillHeight: true
        color: Commons.Color.popups.background
        border.color: Commons.Color.popups.border
        border.width: 1

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.space(root.navigationCollapsed ? 6 : 10)
          spacing: Style.space(6)

          ScrollView {
            id: navigationScroll
            objectName: "navigationScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            rightPadding: ScrollBar.vertical.needed ? root.scrollGutter : 0
            ScrollBar.vertical: ViewScrollBar { view: navigationScroll }

            Column {
              width: navigationScroll.availableWidth
              spacing: Style.space(6)
              Repeater {
                model: root.sectionIds
                delegate: HoverButton {
                  required property string modelData
                  objectName: "navigationButton_" + modelData
                  width: navigationScroll.availableWidth
                  iconOnly: root.navigationCollapsed
                  leftPadding: Style.space(root.navigationCollapsed ? 0 : 10)
                  rightPadding: Style.space(root.newCount(modelData) > 0 ? 24 : 8)
                  leadingIcon: root.navigationCollapsed ? "" : root.sectionIcons[modelData]
                  text: root.navigationCollapsed ? root.sectionIcons[modelData]
                    : root.sectionTitle(modelData)
                      + (modelData === "saved" ? "  " + root.count("saved", "saved")
                        : ["plugins", "themes", "videos", "news", "releases", "community", "events"].indexOf(modelData) >= 0
                        ? "  " + root.count(modelData, "unread") : "")
                  description: root.sectionTitle(modelData) + (modelData === "saved"
                    ? " · " + root.t("dashboard.saved").arg(root.count("saved", "saved")) : "")
                    + (root.newCount(modelData) > 0 ? " · " + root.plural("nav.newItems", root.newCount(modelData)) : "")
                  highlighted: root.currentSection === modelData
                  Rectangle {
                    objectName: "newCountBadge_" + modelData
                    visible: root.newCount(modelData) > 0
                    anchors.right: parent.right
                    anchors.top: parent.top
                    width: Math.max(Style.space(16), newBadgeText.implicitWidth + Style.space(6))
                    height: Style.space(16)
                    radius: height / 2
                    color: Commons.Color.urgent
                    Text {
                      id: newBadgeText
                      objectName: "newBadgeText_" + modelData
                      anchors.centerIn: parent
                      text: root.newCount(modelData) > 9 ? "9+" : String(root.newCount(modelData))
                      textFormat: Text.PlainText
                      color: Commons.Color.popups.background
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                    }
                  }
                  Rectangle {
                    objectName: modelData === "saved" ? "savedCountBadge" : ""
                    visible: root.navigationCollapsed && modelData === "saved" && root.count("saved", "saved") > 0
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: Math.max(Style.space(16), savedBadgeText.implicitWidth + Style.space(6))
                    height: Style.space(16)
                    radius: height / 2
                    color: Commons.Color.accent
                    Text {
                      id: savedBadgeText
                      objectName: "savedBadgeText"
                      anchors.centerIn: parent
                      text: String(root.count("saved", "saved"))
                      textFormat: Text.PlainText
                      color: Commons.Color.popups.background
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                    }
                  }
                  onClicked: root.setSection(modelData)
                }
              }
            }
          }

          Text {
            visible: !root.navigationCollapsed
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.t("privacy.local")
            color: Commons.Color.popups.text
            opacity: 0.65
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }
        }
      }

      Item {
        visible: !root.navigationCollapsed
        Layout.preferredWidth: Style.space(10)
        Layout.fillHeight: true
        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          width: navigationResize.containsMouse || navigationResize.pressed ? 2 : 1
          height: parent.height
          color: navigationResize.containsMouse || navigationResize.pressed
            ? Commons.Color.accent : Commons.Color.popups.border
        }
        Column {
          anchors.centerIn: parent
          spacing: Style.space(3)
          Repeater {
            model: 3
            delegate: Rectangle {
              width: Style.space(3)
              height: width
              radius: width / 2
              color: navigationResize.containsMouse || navigationResize.pressed
                ? Commons.Color.accent : Commons.Color.popups.border
            }
          }
        }
        MouseArea {
          id: navigationResize
          objectName: "navigationResizeHandle"
          anchors.fill: parent
          hoverEnabled: true
          preventStealing: true
          acceptedButtons: Qt.LeftButton
          cursorShape: Qt.SizeHorCursor
          property real startX: 0
          property int startWidth: root.navigationDefaultWidth
          ToolTip.visible: containsMouse && !pressed
          ToolTip.delay: 400
          ToolTip.text: root.t("nav.resize")
          function save() {
            if (root.navigationWidth !== root.savedNavigationWidth)
              root.settingChanged("navigationWidth", String(root.navigationWidth))
          }
          onPressed: function(mouse) {
            startX = mapToItem(root, mouse.x, mouse.y).x
            startWidth = root.effectiveNavigationWidth
          }
          onPositionChanged: function(mouse) {
            if (!pressed) return
            var delta = (mapToItem(root, mouse.x, mouse.y).x - startX)
              * (root.LayoutMirroring.enabled ? -1 : 1)
            root.navigationWidth = Math.max(root.navigationMinWidth, Math.min(root.navigationLimit,
              Math.round(startWidth + delta / (Style.space(1000) / 1000))))
          }
          onReleased: save()
          onDoubleClicked: {
            root.navigationWidth = root.navigationDefaultWidth
            save()
          }
          onCanceled: root.navigationWidth = root.savedNavigationWidth
        }
      }

      ColumnLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.margins: Style.space(12)
        spacing: Style.space(8)

        RowLayout {
          objectName: "sectionHeader"
          Layout.fillWidth: true
          Text {
            objectName: "sectionHeading"
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.sectionTitle(root.currentSection)
            color: Commons.Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
          }
          RowLayout {
            visible: root.sourceIds.concat(["saved", "dashboard"]).indexOf(root.currentSection) >= 0
            HoverButton {
              objectName: "markAllRead"
              text: root.t("actions.allRead")
              description: root.currentSection === "dashboard" ? root.t("actions.allFeedsScope") : ""
              enabled: !root.busy && root.bulkItems.length > 0
              onClicked: root.mutationRequested("mark-all-read", root.currentSection)
            }
            HoverButton {
              objectName: "markAllUnread"
              text: root.t("actions.allUnread")
              description: root.currentSection === "dashboard" ? root.t("actions.allFeedsScope") : ""
              enabled: !root.busy && root.bulkItems.length > 0
              onClicked: root.mutationRequested("mark-all-unread", root.currentSection)
            }
          }
        }

        Text {
          visible: root.status !== ""
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.status
          color: Commons.Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }

        Loader {
          Layout.fillWidth: true
          Layout.fillHeight: true
          sourceComponent: root.currentSection === "dashboard" ? dashboardPage
            : root.currentSection === "settings" ? settingsPage
            : root.currentSection === "system" ? systemPage : listingPage
        }
      }
    }
  }

  Component {
    id: dashboardPage
    ScrollView {
      id: dashboardScroll
      objectName: "dashboardPage"
      clip: true
      contentWidth: availableWidth
      rightPadding: ScrollBar.vertical.needed ? root.scrollGutter : 0
      ScrollBar.vertical: ViewScrollBar { view: dashboardScroll }
      ColumnLayout {
        width: dashboardScroll.availableWidth
        spacing: Style.space(10)

        Component {
          id: systemBriefing
          BriefingPanel {
            RowLayout {
              Layout.fillWidth: true
              spacing: Style.space(8)
              BriefingText {
                Layout.fillWidth: false
                text: root.t("dashboard.systemTitle")
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }
              BriefingText {
                objectName: "dashboardSystemStatus"
                text: root.systemBusy ? root.t("system.checking")
                  : root.systemError || (root.systemData.update || {}).error
                    || ((root.systemData.update || {}).status === "available"
                      ? root.t("system.available").arg((root.systemData.update || {}).detail || "")
                      : (root.systemData.update || {}).status === "none" ? root.t("system.none")
                      : (root.systemData.update || {}).detail || root.t("system.unknown"))
                color: root.systemError || (root.systemData.update || {}).status === "unknown"
                  ? Commons.Color.urgent : Commons.Color.popups.text
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
              }
              HoverButton {
                objectName: "dashboardUpdateButton"
                visible: (root.systemData.update || {}).status === "available"
                text: root.t("system.updateButton")
                enabled: !root.systemBusy && !root.systemError && !root.updateLaunching && !root.updatePending
                onClicked: root.updateRequested()
              }
              HoverButton {
                objectName: "dashboardCheckSystemButton"
                text: root.t("dashboard.checkSystem")
                enabled: !root.systemBusy && !root.updateLaunching
                onClicked: root.systemRequested()
              }
              HoverButton {
                text: root.t("nav.system")
                onClicked: root.setSection("system")
              }
            }
            BriefingText {
              visible: !!(root.systemData.version || {}).error
              text: (root.systemData.version || {}).error || ""
              color: Commons.Color.urgent
              font.pixelSize: Style.font.bodySmall
            }
            BriefingText {
              visible: root.updateLaunching || root.updatePending || root.updateError !== ""
              text: root.updateError || (root.updateLaunching
                ? root.t("system.openingUpdate") : root.t("system.updateRequested").arg(root.updateLog))
              color: root.updateError ? Commons.Color.urgent : Commons.Color.popups.text
              font.pixelSize: Style.font.bodySmall
            }
            BriefingText {
              visible: (root.systemData.update || {}).status === "available"
              text: root.t("system.updateExplanation")
              font.pixelSize: Style.font.bodySmall
              opacity: 0.76
            }
          }
        }
        GridLayout {
          id: briefingGrid
          objectName: "briefingGrid"
          Layout.fillWidth: true
          columns: width < Style.space(640) ? 1 : 2
          columnSpacing: Style.space(10)
          rowSpacing: Style.space(10)
          Repeater {
            model: root.visibleDashboardPanels.filter(function(panel) {
              return root.setting("dashboard_" + panel, true)
            })
            delegate: Loader {
              required property string modelData
              readonly property bool wide: modelData === "system" || modelData === "sources"
              objectName: "dashboardPanel_" + modelData
              Layout.fillWidth: true
              Layout.alignment: Qt.AlignTop
              Layout.columnSpan: wide ? briefingGrid.columns : 1
              Layout.preferredWidth: briefingGrid.columns === 1 || wide ? briefingGrid.width
                : (briefingGrid.width - briefingGrid.columnSpacing) / 2
              Layout.preferredHeight: item ? item.implicitHeight : 0
              sourceComponent: modelData === "system" ? systemBriefing : modelData === "sources" ? sourcesBriefing
                : modelData === "events" ? eventsBriefing : savedBriefing
            }
          }
          Component {
            id: sourcesBriefing
            BriefingPanel {
              title: root.t("dashboard.sources")
              actionText: root.sourceIssues.length > 0 ? root.t("dashboard.retryFailed") : ""
              actionObjectName: "dashboardRetrySourcesButton"
              actionEnabled: !root.busy
              onActionClicked: root.refreshRequested()
              GridLayout {
                id: tileGrid
                Layout.fillWidth: true
                columns: Math.max(1, Math.floor((width + columnSpacing) / (Style.space(150) + columnSpacing)))
                columnSpacing: Style.space(6)
                rowSpacing: Style.space(6)
                uniformCellWidths: true
                Repeater {
                  model: root.dashboardTileSources
                  delegate: SourceTile {
                    required property string modelData
                    section: modelData
                  }
                }
              }
            }
          }
          Component {
            id: eventsBriefing
            BriefingPanel {
              title: root.t("dashboard.upcoming")
              actionText: root.t("dashboard.allEvents")
              onActionClicked: root.setSection("events")
              BriefingText {
                objectName: "dashboardNoEvents"
                visible: root.upcomingItems.length === 0
                text: root.busy ? root.t("actions.loading") : root.t("dashboard.noEvents")
                font.pixelSize: Style.font.bodySmall
                opacity: 0.68
              }
              Repeater {
                model: FeedModel { items: root.upcomingItems.slice(0, 2) }
                delegate: DashboardLink {
                  required property var entry
                  item: entry
                  leadingIcon: root.sectionIcons.events
                  text: entry.name + " · " + root.eventCountdown(entry)
                  tooltipText: root.eventDescription(entry)
                }
              }
            }
          }
          Component {
            id: savedBriefing
            BriefingPanel {
              title: root.t("dashboard.savedUnread").arg(Commons.I18n.formatNumber(root.readingQueue.length))
              actionText: root.t("dashboard.allSaved")
              onActionClicked: root.setSection("saved")
              BriefingText {
                objectName: "dashboardQueueEmpty"
                visible: root.readingQueue.length === 0
                text: root.t("dashboard.queueEmpty")
                font.pixelSize: Style.font.bodySmall
                opacity: 0.68
              }
              Repeater {
                model: FeedModel { items: root.readingQueue.slice(0, 2) }
                delegate: DashboardLink {
                  required property var entry
                  item: entry
                  leadingIcon: root.sectionIcons.saved
                  text: entry.name
                  tooltipText: entry.name + " · " + root.sectionTitle(entry.kind)
                }
              }
              BriefingText {
                objectName: "dashboardQueueMore"
                visible: root.readingQueue.length > 2
                text: root.t("dashboard.moreSaved").arg(Commons.I18n.formatNumber(root.readingQueue.length - 2))
                font.pixelSize: Style.font.bodySmall
                opacity: 0.68
              }
            }
          }
        }
      }
    }
  }

  Component {
    id: listingPage
    ColumnLayout {
      spacing: Style.space(root.compactRows ? 4 : 8)
      RowLayout {
        Layout.fillWidth: true
        ClipboardFreeInput {
          id: filterInput
          objectName: "filterInput"
          Layout.fillWidth: true
          placeholderText: root.t("actions.filter")
          Accessible.description: root.t("actions.filterInputHelp")
          maximumLength: 240
          leftPadding: termsViewport.visible ? termsViewport.width + Style.space(10) : Style.space(8)
          text: String(root.queries[root.currentSection] || "")
          onTextEdited: root.queryChanged(root.currentSection, text)
          onAccepted: root.addFilterTerm(root.currentSection)
          Keys.onPressed: function(event) {
            var terms = root.filterTerms[root.currentSection] || []
            if (event.key === Qt.Key_Backspace && event.modifiers === Qt.NoModifier
                && cursorPosition === 0 && selectionStart === selectionEnd
                && !inputMethodComposing && terms.length > 0) {
              root.removeFilterTerm(root.currentSection, terms.length - 1)
              event.accepted = true
            } else {
              filterInput.editKey(event)
            }
          }

          Flickable {
            id: termsViewport
            objectName: "filterTermsViewport"
            anchors.left: parent.left
            anchors.leftMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(termsRow.implicitWidth, Math.max(0, filterInput.width * 0.6))
            height: Math.max(0, filterInput.height - Style.space(4))
            visible: (root.filterTerms[root.currentSection] || []).length > 0
            contentWidth: termsRow.implicitWidth
            contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            onContentWidthChanged: contentX = Math.max(0, contentWidth - width)
            ScrollBar.horizontal: ScrollBar {
              policy: ScrollBar.AsNeeded
              height: Style.space(4)
            }

            Row {
              id: termsRow
              spacing: Style.space(4)
              Repeater {
                model: root.filterTerms[root.currentSection] || []
                delegate: Rectangle {
                  required property string modelData
                  required property int index
                  width: Math.min(filterInput.width * 0.6, Style.space(200),
                    termLabel.implicitWidth + Style.space(42))
                  height: Math.min(Style.space(28), termsViewport.height)
                  radius: Style.cornerRadius
                  color: "transparent"
                  border.color: Commons.Color.popups.border
                  border.width: 1

                  RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Style.space(8)
                    spacing: Style.space(2)
                    Text {
                      id: termLabel
                      Layout.fillWidth: true
                      text: modelData
                      textFormat: Text.PlainText
                      color: Commons.Color.popups.text
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      elide: Text.ElideRight
                    }
                    OutlineButton {
                      objectName: "removeFilterButton_" + index
                      Layout.preferredWidth: Style.space(28)
                      Layout.minimumHeight: 0
                      Layout.fillHeight: true
                      iconOnly: true
                      text: "×"
                      Accessible.name: root.t("actions.removeFilter").arg(modelData)
                      onClicked: root.removeFilterTerm(root.currentSection, index)
                    }
                  }
                }
              }
            }
          }
        }
        OutlineButton {
          objectName: "addFilterButton"
          leadingIcon: "+"
          text: root.t("actions.addFilter")
          enabled: filterInput.text.trim() !== ""
          onClicked: {
            root.addFilterTerm(root.currentSection)
            filterInput.forceActiveFocus()
          }
        }
        OutlineButton {
          objectName: "openSourceButton"
          visible: root.sectionSource(root.currentSection) !== ""
          text: root.t("actions.openSource")
          onClicked: Qt.openUrlExternally(root.sectionSource(root.currentSection))
        }
      }
      RowLayout {
        readonly property bool dateAvailable: root.currentSection !== "saved" && root.currentSection !== "themes"
          && root.currentSection !== "community"
          && !root.isReference(root.currentSection)
        Layout.fillWidth: true
        Text {
          visible: parent.dateAvailable
          textFormat: Text.PlainText
          text: root.t("listing.dateRange")
          color: Commons.Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        ComboBox {
          visible: parent.dateAvailable
          Layout.fillWidth: true
          model: [root.t("range.all"), root.t("range.today"),
            root.t("range.week"), root.t("range.month")]
          currentIndex: Math.max(0, root.rangeIds.indexOf(root.dateRanges[root.currentSection] || "all"))
          onActivated: function(index) { root.dateRangeChanged(root.currentSection, root.rangeIds[index]) }
        }
        Item {
          visible: !parent.dateAvailable
          Layout.fillWidth: true
        }
        OutlineButton {
          objectName: "readVisibilityButton"
          readonly property bool hiding: root.hideReadBySection[root.currentSection] === true
          text: root.t(hiding ? "actions.showRead" : "actions.hideRead")
          description: root.t(hiding ? "actions.showReadHelp" : "actions.hideReadHelp")
          highlighted: hiding
          onClicked: root.hideReadChanged(root.currentSection, !hiding)
        }
      }
      Text {
        visible: root.filterNotice !== ""
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.filterNotice
        color: Commons.Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
      }
      Text {
        visible: root.currentSection !== "saved" && !!(root.model.errors || {})[root.currentSection]
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: String((root.model.errors || {})[root.currentSection] || "")
        color: Commons.Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.currentSection === "saved"
          ? root.t("listing.savedCount").arg(root.sectionItems("saved").length)
          : root.isReference(root.currentSection)
            ? root.t("listing.referenceCount").arg(root.sectionItems(root.currentSection).length)
            : root.t("listing.status")
              .arg(root.sectionItems(root.currentSection).length)
              .arg(root.count(root.currentSection, "unread"))
        color: Commons.Color.popups.text
        opacity: 0.68
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
      Text {
        visible: root.currentSection === "hotkeys"
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.t("listing.hotkeysDefaults")
        color: Commons.Color.popups.text
        opacity: 0.68
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
      }
      Text {
        visible: root.currentSection === "events"
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.t("listing.eventDates")
        color: Commons.Color.popups.text
        opacity: 0.68
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
      }
      Text {
        visible: root.currentSection === "videos"
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.t("listing.youtubeDates")
        color: Commons.Color.popups.text
        opacity: 0.68
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
      }
      Text {
        visible: !root.busy && root.sectionItems(root.currentSection).length === 0
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.t("listing.empty")
        color: Commons.Color.popups.text
        opacity: 0.68
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      ListView {
        id: listingScroll
        objectName: "listingScroll"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: Style.space(root.compactRows ? 3 : 6)
        readonly property var rows: root.sectionItems(root.currentSection)
        readonly property string filterContext: JSON.stringify([root.currentSection,
          root.queries[root.currentSection], root.filterTerms[root.currentSection],
          root.dateRanges[root.currentSection], root.hideReadBySection[root.currentSection]])
        onFilterContextChanged: Qt.callLater(function() {
          listingScroll.forceLayout()
          listingScroll.positionViewAtBeginning()
        })
        model: FeedModel { items: listingScroll.rows }
        ScrollBar.vertical: ThemedScrollBar { objectName: "listingScrollBar" }
        ReadingTracker {
          viewport: listingScroll
          items: listingScroll.rows
          rowProvider: function() {
            return listingScroll.contentItem.children.filter(function(row) {
              return row.readItem && listingScroll.itemAtIndex(row.index) === row
            })
          }
        }
        delegate: Rectangle {
          required property int index
          required property var entry
          readonly property var modelData: entry
          readonly property var readItem: modelData
          width: listingScroll.width - root.scrollGutter
          implicitHeight: rowContent.implicitHeight + Style.space(root.compactRows ? 8 : 16)
          radius: Style.cornerRadius
          color: Commons.Color.popups.background
          border.color: root.itemBorderColor(modelData)
          border.width: 1

          RowLayout {
            id: rowContent
            anchors.fill: parent
            anchors.margins: Style.space(root.compactRows ? 4 : 8)
            spacing: Style.space(8)

            Rectangle {
              objectName: "itemPreview"
              property string remoteUrl: root.showPreviews ? String(modelData.thumbnail || "") : ""
              onRemoteUrlChanged: if (visible && remoteUrl) root.thumbnailRequested(remoteUrl)
              onVisibleChanged: if (visible && remoteUrl) root.thumbnailRequested(remoteUrl)
              Component.onCompleted: if (visible && remoteUrl) root.thumbnailRequested(remoteUrl)
              visible: root.showPreviews && ["plugins", "themes", "videos", "news", "events"].indexOf(modelData.kind) >= 0
              Layout.preferredWidth: Style.space(root.compactRows ? 80 : 120)
              Layout.preferredHeight: Style.space(root.compactRows ? 50 : 76)
              Layout.alignment: Qt.AlignVCenter
              color: "transparent"
              border.width: 0
              clip: true

              Image {
                id: preview
                objectName: "feedPreviewImage"
                anchors.fill: parent
                source: root.showPreviews ? root.thumbnailSources[parent.remoteUrl] || "" : ""
                onSourceChanged: {
                  if (!source && parent.visible && parent.remoteUrl)
                    root.thumbnailRequested(parent.remoteUrl)
                }
                sourceSize.width: 240
                sourceSize.height: 152
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: status === Image.Ready
                onStatusChanged: if (status === Image.Error) root.thumbnailFailed()
              }
              Text {
                anchors.centerIn: parent
                visible: preview.status !== Image.Ready
                text: "\uf03e"
                textFormat: Text.PlainText
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                color: Commons.Color.popups.text
                opacity: 0.4
              }
            }

            ColumnLayout {
              Layout.fillWidth: true
              spacing: Style.space(4)
              RowLayout {
                Layout.fillWidth: true
                Text {
                  Layout.fillWidth: true
                  textFormat: Text.PlainText
                  text: modelData.name
                  color: Commons.Color.popups.text
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                  font.bold: true
                  wrapMode: Text.Wrap
                  maximumLineCount: 2
                  elide: Text.ElideRight
                }
                Text {
                  visible: !root.isReference(modelData.kind) && modelData.isNew === true
                  textFormat: Text.PlainText
                  text: root.t("listing.new")
                  color: Commons.Color.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }
              }
              Text {
                Layout.fillWidth: true
                objectName: "itemSummary"
                visible: modelData.summary !== "" && !root.compactRows
                textFormat: Text.PlainText
                text: modelData.summary
                color: Commons.Color.popups.text
                opacity: 0.76
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.Wrap
                maximumLineCount: 3
                elide: Text.ElideRight
              }
              Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: [modelData.author, modelData.source,
                  modelData.kind === "themes" || modelData.kind === "community"
                    || root.isReference(modelData.kind) ? "" : modelData.timestamp > 0
                    ? modelData.kind === "events"
                      ? new Date(modelData.timestamp * 1000).toLocaleString(Qt.locale(Commons.I18n.formatLocale), Locale.ShortFormat)
                      : new Date(modelData.timestamp * 1000).toLocaleDateString(Qt.locale(Commons.I18n.formatLocale), Locale.ShortFormat)
                    : root.t("listing.unknownDate"),
                  modelData.kind === "events" ? (modelData.timestamp >= root.currentTime / 1000
                    ? root.t("listing.upcoming") : root.t("listing.started")) : "",
                  modelData.isRead ? root.t("listing.read") : root.t("listing.unread")]
                  .filter(function(value) { return !!value }).join(" · ")
                color: Commons.Color.popups.text
                opacity: 0.62
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }
            }

            ColumnLayout {
              Layout.alignment: Qt.AlignVCenter
              spacing: Style.space(4)
              HoverButton {
                objectName: "itemOpenButton"
                text: root.t("actions.open")
                onClicked: root.openItem(modelData)
              }
              HoverButton {
                objectName: "itemSaveButton"
                text: modelData.isSaved ? root.t("actions.unsave") : root.t("actions.save")
                enabled: !root.busy
                onClicked: root.mutationRequested("toggle-saved", modelData.id)
              }
              HoverButton {
                objectName: "itemReadButton"
                text: modelData.isRead ? root.t("actions.unread") : root.t("actions.read")
                enabled: !root.busy
                onClicked: root.mutationRequested("toggle-read", modelData.id)
              }
            }
          }
        }
      }
    }
  }

  Component {
    id: systemPage
    ScrollView {
      objectName: "systemPage"
      id: systemScroll
      clip: true
      contentWidth: availableWidth
      rightPadding: root.scrollGutter
      ScrollBar.vertical: ViewScrollBar { view: systemScroll }
      ColumnLayout {
        width: systemScroll.availableWidth
        spacing: Style.space(12)
        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.t("system.description")
          color: Commons.Color.popups.text
          opacity: 0.76
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          wrapMode: Text.Wrap
        }
        Text {
          visible: root.systemBusy
          text: root.t("system.checking")
          textFormat: Text.PlainText
          color: Commons.Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Text {
          visible: root.systemError !== ""
          Layout.fillWidth: true
          text: root.systemError
          textFormat: Text.PlainText
          color: Commons.Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }
        Text {
          Layout.fillWidth: true
          text: root.t("system.updateExplanation")
          textFormat: Text.PlainText
          color: Commons.Color.popups.text
          opacity: 0.76
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }
        Text {
          visible: root.updateLaunching || root.updatePending || root.updateError !== ""
          Layout.fillWidth: true
          text: root.updateError || (root.updateLaunching
            ? root.t("system.openingUpdate") : root.t("system.updateRequested").arg(root.updateLog))
          textFormat: Text.PlainText
          color: root.updateError ? Commons.Color.urgent : Commons.Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }
        Repeater {
          model: [
            { key: "version", title: root.t("system.version") },
            { key: "theme", title: root.t("system.theme") },
            { key: "update", title: root.t("system.updates") }
          ]
          delegate: Rectangle {
            required property var modelData
            readonly property var field: modelData.key === "theme" ? root.themeData.current || ({})
              : root.systemData[modelData.key] || ({})
            Layout.fillWidth: true
            implicitHeight: systemRow.implicitHeight + Style.space(20)
            color: "transparent"
            border.color: Commons.Color.popups.border
            border.width: 1
            radius: Style.cornerRadius
            ColumnLayout {
              id: systemRow
              anchors.fill: parent
              anchors.margins: Style.space(10)
              spacing: Style.space(5)
              Text {
                Layout.fillWidth: true
                text: modelData.title
                textFormat: Text.PlainText
                color: Commons.Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                objectName: "systemValue_" + modelData.key
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: modelData.key === "update"
                  ? field.status === "available" ? root.t("system.available").arg(field.detail)
                    : field.status === "none" ? root.t("system.none")
                    : field.detail || root.t("system.unknown")
                  : field.value || field.error || root.t("system.unknown")
                color: field.error || field.status === "unknown"
                  ? Commons.Color.urgent : Commons.Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                wrapMode: Text.Wrap
              }
              Text {
                objectName: modelData.key === "version" ? "systemVersionUpdateStatus" : ""
                visible: modelData.key === "version"
                Layout.fillWidth: true
                text: root.systemBusy ? root.t("system.checking")
                  : root.systemError ? root.t("system.unknown")
                  : (root.systemData.update || {}).status === "available" ? root.t("system.versionAvailable")
                  : (root.systemData.update || {}).status === "none" ? root.t("system.none")
                  : root.t("system.unknown")
                textFormat: Text.PlainText
                color: Commons.Color.popups.text
                opacity: 0.76
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.Wrap
              }
              OutlineButton {
                objectName: modelData.key === "version" || modelData.key === "update"
                  ? "systemUpdateButton_" + modelData.key : ""
                visible: modelData.key === "version" || modelData.key === "update"
                Layout.alignment: Qt.AlignRight
                text: root.t("system.updateButton")
                enabled: !root.systemBusy && !root.systemError && !root.updateLaunching && !root.updatePending
                  && (root.systemData.update || {}).status === "available"
                onClicked: root.updateRequested()
              }
              ComboBox {
                id: themeCombo
                objectName: modelData.key === "theme" ? "systemThemeCombo" : ""
                visible: modelData.key === "theme"
                Layout.fillWidth: true
                enabled: !root.themeBusy && !root.themeError && !root.themeData.listError
                  && !(root.themeData.current || {}).error
                  && model.length > 0
                model: root.themeData.themes || []
                readonly property int actualIndex: model.indexOf((root.themeData.current || {}).value || "")
                currentIndex: actualIndex
                onActualIndexChanged: currentIndex = actualIndex
                onActivated: function(index) {
                  var selected = model[index]
                  currentIndex = actualIndex
                  if (selected && selected !== (root.themeData.current || {}).value)
                    root.themeSelected(selected)
                }
                contentItem: RowLayout {
                  spacing: Style.space(8)
                  ThemeThumbnail {
                    objectName: "themeCurrentPreview"
                    visible: root.showPreviews
                    imageUrl: root.showPreviews ? (root.themeData.previews || {})[themeCombo.currentText] || "" : ""
                  }
                  Text {
                    objectName: "themeCurrentText"
                    Layout.fillWidth: true
                    Layout.rightMargin: themeCombo.indicator ? themeCombo.indicator.width + Style.space(8) : 0
                    text: themeCombo.displayText
                    textFormat: Text.PlainText
                    color: Commons.Color.popups.text
                    opacity: themeCombo.enabled ? 1 : 0.5
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                  }
                }
                delegate: ItemDelegate {
                  required property var modelData
                  required property int index
                  width: themeCombo.width
                  contentItem: RowLayout {
                    spacing: Style.space(8)
                    ThemeThumbnail {
                      objectName: "themeOptionPreview_" + index
                      visible: root.showPreviews
                      imageUrl: themeCombo.popup.visible && root.showPreviews ? (root.themeData.previews || {})[modelData] || "" : ""
                    }
                    Text {
                      Layout.fillWidth: true
                      text: modelData
                      textFormat: Text.PlainText
                      color: Commons.Color.popups.text
                      font.family: Style.font.family
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                      verticalAlignment: Text.AlignVCenter
                    }
                  }
                }
              }
              Text {
                visible: modelData.key === "theme" && root.themeBusy
                Layout.fillWidth: true
                text: root.themeAction === "set" ? root.t("system.applyingTheme") : root.t("system.loadingThemes")
                textFormat: Text.PlainText
                color: Commons.Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                objectName: modelData.key === "theme" ? "systemThemeMessage" : ""
                visible: modelData.key === "theme" && !!(root.themeError || root.themeData.listError
                  || root.themeData.actionError || root.themeData.warning)
                Layout.fillWidth: true
                text: root.themeError || root.themeData.actionError || root.themeData.listError || root.themeData.warning || ""
                textFormat: Text.PlainText
                color: Commons.Color.urgent
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.Wrap
              }
            }
          }
        }
        Text {
          visible: root.systemData.development === true
          Layout.fillWidth: true
          text: root.t("system.development")
          textFormat: Text.PlainText
          color: Commons.Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }
      }
    }
  }

  Component {
    id: settingsPage
    RowLayout {
      id: settingsLayout
      objectName: "settingsPage"
      spacing: Style.space(10)
      readonly property bool compactNavigation: width < Style.space(600)

      ScrollView {
        id: settingsNavigation
        objectName: "settingsNavigation"
        Layout.preferredWidth: Style.space(settingsLayout.compactNavigation ? 44 : 172)
        Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth
        rightPadding: ScrollBar.vertical.needed ? root.scrollGutter : 0
        ScrollBar.vertical: ViewScrollBar { view: settingsNavigation }
        Column {
          width: settingsNavigation.availableWidth
          spacing: Style.space(4)
          Repeater {
            model: root.settingsSections
            delegate: HoverButton {
              required property string modelData
              objectName: "settingsNav_" + modelData
              width: settingsNavigation.availableWidth
              readonly property string sectionIcon: modelData === "general" ? "\uf1de"
                : modelData === "sections" ? "\uf0c0"
                : modelData === "help" ? "\uf059"
                : modelData === "refresh" ? "\uf021" : root.sectionIcons[modelData]
              iconOnly: settingsLayout.compactNavigation
              leadingIcon: iconOnly ? "" : sectionIcon
              text: iconOnly ? sectionIcon : root.settingsSectionTitle(modelData)
              description: root.settingsSectionTitle(modelData)
              highlighted: root.currentSettingsSection === modelData
              onClicked: root.currentSettingsSection = modelData
            }
          }
        }
      }
      Rectangle {
        Layout.fillHeight: true
        implicitWidth: 1
        color: Commons.Color.popups.border
      }
      Connections {
        target: root
        function onCurrentSettingsSectionChanged() {
          settingsScroll.contentItem.contentY = 0
        }
      }
      ScrollView {
        id: settingsScroll
        objectName: "settingsContentScroll"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth
        rightPadding: root.scrollGutter
        ScrollBar.vertical: ViewScrollBar { view: settingsScroll }
        ColumnLayout {
          width: settingsScroll.availableWidth
          spacing: Style.space(12)
          Loader {
            id: settingsContent
            objectName: "settingsContent"
            Layout.fillWidth: true
            sourceComponent: root.currentSettingsSection === "general" ? appearanceSettings
              : root.currentSettingsSection === "sections" ? sectionVisibilitySettings
              : root.currentSettingsSection === "help" ? helpSettings
              : root.currentSettingsSection === "refresh" ? refreshSettings
              : root.currentSettingsSection === "dashboard" ? dashboardSettings : sectionSettings
            onLoaded: settingsScroll.contentItem.contentY = 0
          }
        }
      }
    }
  }

  Component {
    id: helpSettings
    BriefingPanel {
      title: root.t("settings.help")
      BriefingText {
        objectName: "pluginVersionLabel"
        text: root.pluginVersion ? root.t("settings.pluginVersion").arg(root.pluginVersion)
          : root.t("actions.loading")
      }
      BriefingText {
        text: root.t("settings.feedbackHelp")
        font.pixelSize: Style.font.bodySmall
        opacity: 0.76
      }
      HoverButton {
        objectName: "reportBugButton"
        text: root.t("settings.reportBug")
        enabled: root.pluginVersion !== ""
        onClicked: root.reportIssue("bug_report.yml")
      }
      HoverButton {
        objectName: "requestFeatureButton"
        text: root.t("settings.requestFeature")
        enabled: root.pluginVersion !== ""
        onClicked: root.reportIssue("feature_request.yml")
      }
    }
  }

  Component {
    id: appearanceSettings
    BriefingPanel {
      title: root.t("settings.general")
      TogglePreference { settingKey: "showPreviews"; label: root.t("settings.previews") }
      TogglePreference { settingKey: "markReadOnOpen"; label: root.t("settings.markReadOnOpen") }
      TogglePreference { settingKey: "markReadOnScroll"; label: root.t("settings.markReadOnScroll") }
      ChoicePreference {
        settingKey: "density"
        label: root.t("settings.density")
        values: ["comfortable", "compact"]
        labels: [root.t("settings.comfortable"), root.t("settings.compact")]
      }
      HoverButton {
        objectName: "reset_general"
        text: root.t("settings.defaults")
        enabled: !root.busy
        onClicked: root.settingsResetRequested("general")
      }
    }
  }

  Component {
    id: sectionVisibilitySettings
    ColumnLayout {
      Layout.fillWidth: true
      spacing: Style.space(10)
      BriefingPanel {
        title: root.t("settings.sections")
        BriefingText {
          text: root.t("settings.sectionsHelp")
          font.pixelSize: Style.font.bodySmall
          opacity: 0.76
        }
        BriefingText { text: root.t("settings.sectionFeeds"); font.bold: true }
        Repeater {
          model: root.briefingSources.concat(["events"])
          delegate: TogglePreference {
            required property string modelData
            settingKey: "section_" + modelData
            label: root.sectionTitle(modelData)
          }
        }
      }
      BriefingPanel {
        title: root.t("settings.sectionReference")
        Repeater {
          model: ["manual", "hotkeys", "system"]
          delegate: TogglePreference {
            required property string modelData
            settingKey: "section_" + modelData
            label: root.sectionTitle(modelData)
          }
        }
      }
      BriefingPanel {
        title: root.t("settings.alwaysAvailable")
        BriefingText {
          text: [root.sectionTitle("dashboard"), root.sectionTitle("saved"),
            root.sectionTitle("settings")].join(" · ")
          wrapMode: Text.Wrap
        }
      }
      HoverButton {
        objectName: "reset_sections"
        text: root.t("settings.defaults")
        enabled: !root.busy
        onClicked: root.settingsResetRequested("sections")
      }
    }
  }

  Component {
    id: refreshSettings
    BriefingPanel {
      title: root.t("settings.refresh")
      BriefingText {
        text: root.t("settings.refreshHelp")
        font.pixelSize: Style.font.bodySmall
        opacity: 0.76
      }
      TogglePreference { settingKey: "periodicRefresh"; label: root.t("settings.periodicRefresh") }
      TogglePreference { settingKey: "newItemNotifications"; label: root.t("settings.newItemNotifications") }
      ChoicePreference {
        settingKey: "refreshInterval"
        label: root.t("settings.refreshInterval")
        values: [10, 15, 20, 30, 45, 60]
        labels: [10, 15, 20, 30, 45, 60].map(function(minutes) {
          return root.t("settings.minutes").arg(minutes)
        })
        defaultValue: 30
      }
      TogglePreference {
        visible: root.sectionEnabled("videos")
        settingKey: "periodicVideos"
        label: root.t("settings.periodicVideos")
        defaultValue: false
      }
      BriefingText {
        text: root.t("settings.periodicFootnote")
        font.pixelSize: Style.font.bodySmall
        opacity: 0.76
      }
      TogglePreference { settingKey: "refreshOnOpen"; label: root.t("settings.refreshOnOpen") }
      Repeater {
        model: root.visibleSourceIds
        delegate: TogglePreference {
          required property string modelData
          settingKey: "refresh_" + modelData
          label: root.sectionTitle(modelData)
        }
      }
      TogglePreference {
        visible: root.sectionEnabled("system")
        settingKey: "systemCheckOnOpen"
        label: root.t("settings.systemAuto")
      }
      HoverButton {
        objectName: "reset_refresh"
        text: root.t("settings.defaults")
        enabled: !root.busy
        onClicked: root.settingsResetRequested("refresh")
      }
    }
  }

  Component {
    id: dashboardSettings
    BriefingPanel {
      title: root.t("nav.dashboard")
      BriefingText {
        text: root.t("settings.dashboardHelp")
        font.pixelSize: Style.font.bodySmall
        opacity: 0.76
      }
      Repeater {
        model: root.visibleDashboardPanels
        delegate: RowLayout {
          required property string modelData
          required property int index
          Layout.fillWidth: true
          TogglePreference {
            settingKey: "dashboard_" + parent.modelData
            label: root.dashboardPanelTitle(parent.modelData)
          }
          HoverButton {
            objectName: "dashboardUp_" + parent.modelData
            text: "\uf062"
            description: root.t("settings.moveUp")
            enabled: !root.busy && parent.index > 0
            onClicked: root.moveDashboardPanel(parent.modelData, -1)
          }
          HoverButton {
            objectName: "dashboardDown_" + parent.modelData
            text: "\uf063"
            description: root.t("settings.moveDown")
            enabled: !root.busy && parent.index < root.visibleDashboardPanels.length - 1
            onClicked: root.moveDashboardPanel(parent.modelData, 1)
          }
        }
      }
      HoverButton {
        objectName: "reset_dashboard"
        text: root.t("settings.defaults")
        enabled: !root.busy
        onClicked: root.settingsResetRequested("dashboard")
      }
    }
  }

  Component {
    id: sectionSettings
    BriefingPanel {
      id: sectionPreferences
      property bool confirmingRemoval: false
      title: root.sectionTitle(root.currentSettingsSection)
      Connections {
        target: root
        function onCurrentSettingsSectionChanged() { sectionPreferences.confirmingRemoval = false }
        function onCurrentSectionChanged() { sectionPreferences.confirmingRemoval = false }
      }
      BriefingText {
        text: root.t("settings.filtersHelp")
        font.pixelSize: Style.font.bodySmall
        opacity: 0.76
      }
      TogglePreference {
        settingKey: "remember_" + root.currentSettingsSection
        label: root.t("settings.rememberFilters")
      }
      ChoicePreference {
        visible: root.currentSettingsSection === "videos"
        settingKey: "videosLimit"; label: root.t("settings.videosLimit")
        values: [50, 100, 150]; defaultValue: 100
      }
      BriefingText {
        visible: root.currentSettingsSection === "videos"
        text: root.t("settings.networkNote")
        font.pixelSize: Style.font.bodySmall
        opacity: 0.65
      }
      HoverButton {
        objectName: "reset_" + root.currentSettingsSection
        text: root.t("settings.sectionDefaults")
        enabled: !root.busy
        onClicked: root.settingsResetRequested(root.currentSettingsSection)
      }
      ColumnLayout {
        visible: root.currentSettingsSection === "saved"
        Layout.fillWidth: true
        Layout.topMargin: Style.space(12)
        spacing: Style.space(8)
        BriefingText {
          text: root.t("settings.clearSavedHelp")
          font.pixelSize: Style.font.bodySmall
          opacity: 0.76
        }
        HoverButton {
          objectName: "clearSavedButton"
          visible: !sectionPreferences.confirmingRemoval
          text: root.t("settings.clearSaved")
          enabled: !root.busy && root.count("saved", "saved") > 0
          onClicked: sectionPreferences.confirmingRemoval = true
        }
        BriefingText {
          objectName: "clearSavedConfirmation"
          visible: sectionPreferences.confirmingRemoval
          text: root.translations ? root.translations.tn("settings.clearSavedConfirm", root.count("saved", "saved"))
            .arg(Qt.locale(Commons.I18n.formatLocale).toString(root.count("saved", "saved"), "f", 0))
            : "settings.clearSavedConfirm"
          color: Commons.Color.urgent
        }
        RowLayout {
          visible: sectionPreferences.confirmingRemoval
          Layout.fillWidth: true
          HoverButton {
            objectName: "cancelClearSavedButton"
            text: root.t("actions.cancel")
            onClicked: sectionPreferences.confirmingRemoval = false
          }
          OutlineButton {
            objectName: "confirmClearSavedButton"
            text: root.t("settings.clearSaved")
            enabled: !root.busy && root.count("saved", "saved") > 0
            onClicked: {
              sectionPreferences.confirmingRemoval = false
              root.clearSavedRequested()
            }
          }
        }
      }
    }
  }
}
