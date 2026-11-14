import QtQuick
import Quickshell.Io

Item {
  id: root
  visible: false
  property var command: []
  property int timeoutMs: 120000
  property string timeoutExecutable: "/usr/bin/timeout"
  property bool running: false
  property bool settled: true
  property bool started: false
  signal completed(int exitCode, string output, string errorOutput)

  function finish(exitCode, output, errorOutput) {
    if (settled) return
    settled = true
    watchdog.stop()
    startup.stop()
    running = false
    completed(exitCode, output, errorOutput)
  }

  onRunningChanged: {
    if (!running || !settled) return
    settled = false
    started = false
    // GNU timeout also terminates descendants if a backend operation stalls.
    child.command = [timeoutExecutable, "--signal=TERM", "--kill-after=2s",
      String(timeoutMs / 1000) + "s"].concat(command)
    watchdog.restart()
    startup.restart()
    child.running = true
  }

  Process {
    id: child
    stdout: StdioCollector { id: output; waitForEnd: true }
    stderr: StdioCollector { id: errors; waitForEnd: true }
    onStarted: { root.started = true; startup.stop() }
    onExited: function(exitCode) {
      root.finish(exitCode, String(output.text || ""), exitCode === 124 || exitCode === 137
        ? "The helper operation timed out." : String(errors.text || ""))
    }
  }
  Timer {
    id: startup
    interval: 2000
    onTriggered: {
      if (!root.started) {
        if (child.running) child.signal(9)
        root.finish(1, "", "Could not start the helper process.")
      }
    }
  }
  Timer {
    id: watchdog
    interval: root.timeoutMs + 4000
    onTriggered: {
      if (child.running) child.signal(9)
      root.finish(1, "", "The helper operation timed out.")
    }
  }
}
