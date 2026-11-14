import QtQuick
import Quickshell
import "." as Plugin

Scope {
  id: root
  property int stage: 0
  property int completions: 0
  function require(condition, message) {
    if (!condition) {
      console.error("PROCESS TEST FAILED: " + message)
      Qt.quit()
      return false
    }
    return true
  }
  Plugin.BoundedProcess {
    id: helper
    timeoutMs: 100
    onCompleted: function(exitCode, output, errorOutput) {
      root.completions++
      if (!root.require(!running, "running state did not settle")) return
      if (root.stage === 0) {
        if (!root.require(exitCode !== 0 && errorOutput.length > 0, "failed start not reported")) return
        root.stage = 1
        helper.timeoutExecutable = "/usr/bin/timeout"
        Qt.callLater(function() { helper.command = ["printf", "recovered"]; helper.running = true })
      } else if (root.stage === 1) {
        if (!root.require(exitCode === 0 && output === "recovered", "retry did not succeed")) return
        root.stage = 2
        Qt.callLater(function() { helper.command = ["sleep", "10"]; helper.running = true })
      } else if (root.stage === 2) {
        if (!root.require(exitCode !== 0 && errorOutput === "The helper operation timed out.",
            "deadline did not settle")) return
        root.stage = 3
        delay.start()
      } else {
        root.require(false, "operation settled more than once")
      }
    }
  }
  Timer {
    id: delay
    interval: 200
    onTriggered: {
      if (root.require(root.completions === 3, "duplicate completion")) {
        console.log("PROCESS TEST PASSED")
        Qt.quit()
      }
    }
  }
  Component.onCompleted: {
    helper.timeoutExecutable = "/nonexistent/all-things-omarchy-test"
    helper.command = ["printf", "unreachable"]
    helper.running = true
  }
}
