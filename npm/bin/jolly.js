#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { findPython } = require("../python");

const root = path.resolve(__dirname, "..", "..");
const runtime = path.join(root, ".jolly-python");
const marker = path.join(runtime, ".installed-version");
if (!fs.existsSync(marker)) {
  console.error("Jolly is preparing its local Python runtime for the first command.");
  const installer = spawnSync(process.execPath, [path.join(root, "npm", "install.js")], {
    stdio: ["inherit", 2, 2],
    cwd: root,
  });
  if (installer.status !== 0 || !fs.existsSync(marker)) {
    console.error("Jolly Python runtime setup failed. Run `npm rebuild jolly-cli` after fixing Python or pip.");
    process.exit(installer.status || 1);
  }
}

const python = findPython();
if (!python) {
  console.error("Jolly requires Python 3.10 or later.");
  process.exit(1);
}

const separator = process.platform === "win32" ? ";" : ":";
const existingPath = process.env.PYTHONPATH;
const env = {
  ...process.env,
  PYTHONPATH: existingPath ? `${runtime}${separator}${existingPath}` : runtime,
};
const result = spawnSync(
  python.command,
  [...python.prefix, "-m", "jolly", ...process.argv.slice(2)],
  { stdio: "inherit", env }
);
if (result.error) {
  console.error(`Jolly failed to start: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
