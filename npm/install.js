#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { findPython } = require("./python");

if (process.env.JOLLY_SKIP_PYTHON_INSTALL === "1") {
  console.log("Jolly: skipped Python runtime installation (JOLLY_SKIP_PYTHON_INSTALL=1).");
  process.exit(0);
}

const root = path.resolve(__dirname, "..");
const runtime = path.join(root, ".jolly-python");
const marker = path.join(runtime, ".installed-version");
const version = require(path.join(root, "package.json")).version;

if (fs.existsSync(marker) && fs.readFileSync(marker, "utf8").trim() === version) {
  console.log(`Jolly: Python runtime ${version} is ready.`);
  process.exit(0);
}

const python = findPython();
if (!python) {
  console.error("Jolly requires Python 3.10 or later. Install Python, then run npm rebuild jolly-cli.");
  process.exit(1);
}

fs.rmSync(runtime, { recursive: true, force: true });
fs.mkdirSync(runtime, { recursive: true });
console.log("Jolly: installing the local Python physics runtime. This can take several minutes.");
const args = [
  ...python.prefix,
  "-m",
  "pip",
  "install",
  "--disable-pip-version-check",
  "--no-input",
  "--target",
  runtime,
  root,
];
const result = spawnSync(python.command, args, { stdio: "inherit", cwd: root });
if (result.status !== 0) {
  console.error("Jolly: Python runtime installation failed.");
  process.exit(result.status || 1);
}
fs.writeFileSync(marker, `${version}\n`, "utf8");
console.log("Jolly: installation complete. Run `jolly state --json`.");
