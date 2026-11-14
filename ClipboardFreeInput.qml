import QtQuick
import QtQuick.Controls

TextField {
  id: root
  // Editable Qt inputs request clipboard text even without a paste action.
  // Keep the native input read-only and apply bounded key edits ourselves.
  readOnly: true
  selectByMouse: false
  cursorDelegate: Rectangle {
    width: 1
    color: root.color
    visible: root.activeFocus
  }
  Keys.priority: Keys.BeforeItem
  function editKey(event) {
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      accepted()
      event.accepted = true
      return
    }
    if (event.matches(StandardKey.Paste) || event.matches(StandardKey.Cut)) {
      event.accepted = true
      return
    }
    var start = selectionStart
    var end = selectionEnd
    var replacement = ""
    var deleting = event.key === Qt.Key_Backspace || event.key === Qt.Key_Delete
    if (deleting) {
      if (start === end) {
        if (event.key === Qt.Key_Backspace && start > 0) {
          start--
          if (start > 0 && text.charCodeAt(start) >= 0xdc00
              && text.charCodeAt(start) <= 0xdfff) start--
        } else if (event.key === Qt.Key_Delete && end < text.length) {
          end++
          if (text.charCodeAt(end - 1) >= 0xd800
              && text.charCodeAt(end - 1) <= 0xdbff) end++
        }
      }
    } else if (event.text && !(event.modifiers & Qt.MetaModifier)
        && (!(event.modifiers & Qt.ControlModifier) || (event.modifiers & Qt.AltModifier))
        && !/[\u0000-\u001f\u007f]/.test(event.text)) {
      replacement = event.text.slice(0, maximumLength - (text.length - (end - start)))
    } else {
      return
    }
    var previous = text
    remove(start, end)
    insert(start, replacement)
    cursorPosition = start + replacement.length
    if (text !== previous) textEdited()
    event.accepted = true
  }
}
