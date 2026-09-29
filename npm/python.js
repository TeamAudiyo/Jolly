"use strict";

const { spawnSync } = require("node:child_process");

function pythonCandidates() {
  const configured = process.env.JOLLY_PYTHON;
  const defaults = process.platform === "win32" ? ["py", "python"] : ["python3", "python"];
  return configured ? [configured, ...defaults] : defaults;
}

function findPython() {
  for (const command of pythonCandidates()) {
    const args = command === "py" ? ["-3", "-c", "import sys; print(sys.executable)"] : ["-c", "import sys; print(sys.executable)"];
    const result = spawnSync(command, args, { encoding: "utf8" });
    if (result.status === 0) {
      return { command, prefix: command === "py" ? ["-3"] : [] };
    }
  }
  return null;
}

module.exports = { findPython };
