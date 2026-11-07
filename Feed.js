.pragma library

function addTerm(terms, value) {
  var result = []
  if (terms && typeof terms !== "string" && typeof terms.length === "number")
    for (var index = 0; index < terms.length; ++index) result.push(terms[index])
  var term = String(value || "").trim()
  if (term && !result.some(function(existing) {
    return existing.toLocaleLowerCase() === term.toLocaleLowerCase()
  })) result.push(term)
  return result
}

function filterItems(items, range, query, currentTime, sortByDate, includeFuture) {
  var rows = Array.isArray(items) ? items.slice() : []
  if (range !== "all") {
    var start = new Date(currentTime)
    start.setHours(0, 0, 0, 0)
    if (range === "week") start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
    else if (range === "month") start.setDate(1)
    var cutoff = start.getTime() / 1000
    var end = new Date(start)
    if (range === "week") end.setDate(end.getDate() + 7)
    else if (range === "month") end.setMonth(end.getMonth() + 1)
    else end.setDate(end.getDate() + 1)
    rows = rows.filter(function(item) {
      var timestamp = Number(item.timestamp || 0)
      return timestamp >= cutoff && (includeFuture
        ? timestamp < end.getTime() / 1000 : timestamp <= currentTime / 1000)
    })
  }
  var values = []
  if (query && typeof query !== "string" && typeof query.length === "number") {
    for (var index = 0; index < query.length; ++index) values.push(query[index])
  } else {
    values.push(query)
  }
  var terms = values.map(function(term) {
    return String(term || "").trim().toLocaleLowerCase()
  }).filter(function(term) { return term !== "" })
  if (terms.length) {
    rows = rows.filter(function(item) {
      var text = [item.name, item.summary, item.searchText, item.author, item.source].join(" ").toLocaleLowerCase()
      return terms.every(function(term) { return text.indexOf(term) !== -1 })
    })
  }
  if (sortByDate !== false)
    rows.sort(function(a, b) { return Number(b.timestamp || 0) - Number(a.timestamp || 0) })
  return rows
}
