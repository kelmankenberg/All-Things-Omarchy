pragma Singleton
import QtQuick

QtObject {
  property var font: ({ family: "monospace", body: 14, bodySmall: 12, subtitle: 16, title: 18, icon: 16 })
  property int cornerRadius: 4
  function space(value) { return value }
  function hoverFillFor(foreground, accent) { return Qt.rgba(1, 0.5, 0, 0.2) }
  function focusFillFor(foreground, accent) { return Qt.rgba(1, 0.5, 0, 0.3) }
}
