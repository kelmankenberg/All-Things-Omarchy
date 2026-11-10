import QtQuick

ListModel {
  id: root
  dynamicRoles: true
  property var items: []

  function syncItems() {
    var sameOrder = count === items.length
    for (var index = 0; sameOrder && index < count; index++) {
      if (get(index).entry.id !== items[index].id) sameOrder = false
    }
    if (!sameOrder) {
      clear()
      for (var row = 0; row < items.length; row++) append({ entry: items[row] })
    } else {
      for (var update = 0; update < items.length; update++) {
        setProperty(update, "entry", items[update])
      }
    }
  }

  onItemsChanged: syncItems()
  Component.onCompleted: syncItems()
}
