import QtQuick
import QtTest
import "../Feed.js" as Feed

TestCase {
  name: "FeedFilters"
  property var items: []
  property double now: 0

  function timestamp(year, month, day, hour) {
    return new Date(year, month - 1, day, hour || 0).getTime() / 1000
  }

  function init() {
    now = timestamp(2020, 5, 6, 12) * 1000
    items = [
      { name: "Last month", timestamp: timestamp(2020, 4, 30) },
      { name: "Yesterday", timestamp: timestamp(2020, 5, 5) },
      { name: "No date", timestamp: 0 },
      { name: "Today", timestamp: timestamp(2020, 5, 6, 10) },
      { name: "Earlier this month", timestamp: timestamp(2020, 5, 1) }
    ]
  }

  function names(range, query) {
    return Feed.filterItems(items, range, query || "", now)
      .map(function(item) { return item.name }).join(",")
  }

  function test_dateRangesAndOrder() {
    compare(names("all"), "Today,Yesterday,Earlier this month,Last month,No date")
    compare(names("today"), "Today")
    compare(names("week"), "Today,Yesterday")
    compare(names("month"), "Today,Yesterday,Earlier this month")
  }

  function test_dateRangeCombinesWithTextFilter() {
    compare(names("month", "yesterday"), "Yesterday")
  }

  function test_eventRangesIncludeFutureDatesWithinLocalCalendarPeriod() {
    var events = [
      { name: "Later today", timestamp: timestamp(2020, 5, 6, 18) },
      { name: "Tomorrow", timestamp: timestamp(2020, 5, 7, 10) },
      { name: "Next week", timestamp: timestamp(2020, 5, 11, 10) },
      { name: "Next month", timestamp: timestamp(2020, 6, 1, 10) }
    ]
    function filtered(range) {
      return Feed.filterItems(events, range, "", now, false, true)
        .map(function(item) { return item.name }).join(",")
    }
    compare(filtered("today"), "Later today")
    compare(filtered("week"), "Later today,Tomorrow")
    compare(filtered("month"), "Later today,Tomorrow,Next week")
    compare(Feed.filterItems(events, "today", "", now, false).length, 0)
  }

  function test_siteOrderIsPreservedWithoutDateSorting() {
    var rows = Feed.filterItems(items, "all", "", now, false)
    compare(rows.map(function(item) { return item.name }).join(","),
      "Last month,Yesterday,No date,Today,Earlier this month")
  }

  function test_fullManualTextIsSearchableBeyondTheSummary() {
    var reference = [{ name: "Manual", summary: "Short preview", searchText: "A longer chapter about monitors" }]
    compare(Feed.filterItems(reference, "all", "monitors", now, false).length, 1)
  }

  function test_termsCombineAcrossFieldsAndRespectDateRange() {
    var rows = [
      { name: "Dark Ocean", author: "Alice", timestamp: timestamp(2020, 5, 6, 10) },
      { name: "Dark Forest", author: "Bob", timestamp: timestamp(2020, 5, 6, 9) },
      { name: "Ocean", author: "Alice", timestamp: timestamp(2020, 4, 30) }
    ]
    compare(Feed.filterItems(rows, "today", ["dark", "ALICE"], now).length, 1)
    compare(Feed.filterItems(rows, "all", ["ocean", "alice"], now).length, 2)
    compare(Feed.filterItems(rows, "today", ["ocean", "alice"], now).length, 1)
    compare(Feed.filterItems(rows, "all", ["dark forest"], now)[0].author, "Bob")
    compare(Feed.filterItems(rows, "all", ["dark", "missing"], now).length, 0)
    compare(Feed.filterItems(rows, "all", ["", "  "], now).length, 3)
  }

  function test_addingTermsTrimsAndAvoidsDuplicates() {
    var terms = Feed.addTerm([], "  Dark Ocean  ")
    terms = Feed.addTerm(terms, "dark ocean")
    terms = Feed.addTerm(terms, "   ")
    terms = Feed.addTerm(terms, "blue")
    compare(terms.join("|"), "Dark Ocean|blue")
  }
}
