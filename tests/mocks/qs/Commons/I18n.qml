pragma Singleton
import QtQuick

QtObject {
  property string formatLocale: "en_US"
  function formatNumber(value) { return String(value) }
}
