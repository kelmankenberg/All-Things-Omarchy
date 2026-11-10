.pragma library

function newlyDiscovered(previousItems, nextItems, sections, enabled) {
  var oldIds = ({})
  var result = ({})
  sections.forEach(function(section) {
    oldIds[section] = [];
    (previousItems[section] || []).forEach(function(item) {
      var id = String(item.id || "")
      if (item.isNew === true && id) oldIds[section].push(id)
    })
    result[section] = 0
  })
  if (enabled === false) return result
  sections.forEach(function(section) {
    (nextItems[section] || []).forEach(function(item) {
      var id = String(item.id || "")
      if (item.isNew === true && id && oldIds[section].indexOf(id) === -1) result[section]++
    })
  })
  return result
}

function escapeMarkup(value) {
  return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}
