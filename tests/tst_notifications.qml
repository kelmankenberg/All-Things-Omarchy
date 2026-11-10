import QtQuick
import QtTest
import "../Notifications.js" as Notifications

TestCase {
  name: "Notifications"

  function test_groupNewItemsAcrossSectionsAndIgnoreExistingNewItems() {
    var counts = Notifications.newlyDiscovered({
      plugins: [{ id: "plugins:old", isNew: true }],
      news: [{ id: "news:read", isNew: false }]
    }, {
      plugins: [
        { id: "plugins:old", isNew: true },
        { id: "plugins:new", isNew: true }
      ],
      news: [
        { id: "news:read", isNew: false },
        { id: "news:new-a", isNew: true },
        { id: "news:new-b", isNew: true }
      ]
    }, ["plugins", "news"])

    compare(counts.plugins, 1)
    compare(counts.news, 2)
  }

  function test_notificationsCanBeDisabled() {
    var counts = Notifications.newlyDiscovered({}, {
      plugins: [{ id: "plugins:new", isNew: true }]
    }, ["plugins"], false)

    compare(counts.plugins, 0)
  }

  function test_sectionNamesAreEscapedForNotificationMarkup() {
    compare(Notifications.escapeMarkup("News & <Themes>"), "News &amp; &lt;Themes&gt;")
  }
}
