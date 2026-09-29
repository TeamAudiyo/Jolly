#!/usr/bin/env node
"use strict";

const path = require("node:path");
const { spawnSync } = require("node:child_process");

const executable = path.join(__dirname, "bin", "jolly.js");
const result = spawnSync(process.execPath, [executable, "models", "--json"], { encoding: "utf8" });
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout);
  process.exit(result.status || 1);
}
const data = JSON.parse(result.stdout);
if (!data.ok || !Array.isArray(data.models) || data.models.length < 2) {
  throw new Error("Jolly npm wrapper returned an invalid model response.");
}
console.log(`Jolly npm wrapper is ready with ${data.models.length} robot models.`);
