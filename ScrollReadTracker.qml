import QtQuick

Item {
  id: root
  required property Flickable viewport
  required property var rowProvider
  required property var items
  property bool tracking: false
  property bool busy: false
  property string contextKey: ""
  property var viewedRows: []
  property var pendingReads: []
  property real previousY: 0
  property bool layoutPending: false
  readonly property string contentOrder: JSON.stringify((items || []).map(function(item) {
    return item.id
  }))
  signal readRequested(var ids)

  function resetReading() {
    viewedRows = []
    pendingReads = []
    previousY = viewport ? viewport.contentY : 0
    Qt.callLater(sampleRows)
  }

  function sampleRows() {
    if (!tracking || layoutPending || !viewport || !viewport.contentItem) return
    var top = viewport.contentY
    var viewed = []
    var rows = rowProvider()
    for (var index = 0; index < rows.length; index++) {
      var row = rows[index]
      if (!row.readItem || !row.visible) continue
      var y = row.mapToItem(viewport.contentItem, 0, 0).y
      if (y + row.height <= top || y >= top + viewport.height) continue
      viewed.push({ id: row.readItem.id, bottom: y + row.height,
        isRead: row.readItem.isRead === true })
    }
    var visibleIds = viewed.map(function(row) { return row.id })
    var pending = pendingReads.filter(function(row) {
      return top >= row.bottom && visibleIds.indexOf(row.id) < 0
    })
    if (top > previousY) {
      viewedRows.forEach(function(row) {
        if (!row.isRead && row.bottom <= top && visibleIds.indexOf(row.id) < 0
            && !pending.some(function(entry) { return entry.id === row.id }))
          pending.push({ id: row.id, bottom: row.bottom, due: Date.now() + 1000 })
      })
    }
    viewedRows = viewed
    pendingReads = pending
    previousY = top
  }

  onTrackingChanged: resetReading()
  onContentOrderChanged: {
    layoutPending = true
    resetReading()
    layoutTimer.restart()
  }
  onContextKeyChanged: resetReading()
  onItemsChanged: Qt.callLater(sampleRows)
  Component.onCompleted: Qt.callLater(sampleRows)
  Timer {
    id: layoutTimer
    interval: 0
    onTriggered: {
      root.layoutPending = false
      root.resetReading()
    }
  }
  Connections {
    target: root.viewport
    function onContentYChanged() { root.sampleRows() }
    function onContentHeightChanged() { Qt.callLater(root.sampleRows) }
    function onHeightChanged() { root.resetReading() }
    function onWidthChanged() { root.resetReading() }
  }
  Timer {
    interval: 100
    running: root.tracking && !root.layoutPending && root.pendingReads.length > 0
    repeat: true
    onTriggered: {
      root.sampleRows()
      if (root.busy) return
      var unreadIds = root.items.filter(function(item) { return !item.isRead })
        .map(function(item) { return item.id })
      var ready = root.pendingReads.filter(function(row) {
        return row.due <= Date.now() && unreadIds.indexOf(row.id) >= 0
      }).slice(0, 200).map(function(row) { return row.id })
      root.pendingReads = root.pendingReads.filter(function(row) {
        return ready.indexOf(row.id) < 0 && unreadIds.indexOf(row.id) >= 0
      })
      if (ready.length > 0) root.readRequested(ready)
    }
  }
}
