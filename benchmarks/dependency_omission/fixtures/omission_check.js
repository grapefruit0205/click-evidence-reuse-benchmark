const fs = require("node:fs");
const { spawnSync } = require("node:child_process");

function mark(path) {
  console.log(`CLICK_BENCH_DEP=${path}`);
}

function readText(path) {
  mark(path);
  try {
    return fs.readFileSync(path.replace(/\/$/, ""), "utf8");
  } catch (_error) {
    return null;
  }
}

function parseSpec() {
  const value = readText("case.spec");
  if (value === null) return {};
  return Object.fromEntries(
    value.split(/\r?\n/).filter((line) => line.includes("=")).map((line) => line.split(/=(.*)/s, 2)),
  );
}

function child(path, expected) {
  return readText(path) === expected ? 0 : 1;
}

function main() {
  if (process.argv.length === 5 && process.argv[2] === "--child") {
    return child(process.argv[3], process.argv[4]);
  }
  const spec = parseSpec();
  if (readText("stable.txt") !== "stable-control") return 1;
  const mode = spec.mode;
  const expected = spec.expected || "";
  if (mode === "direct-file") return readText(spec.target) === expected ? 0 : 1;
  if (mode === "nested-pointer") {
    const target = readText(spec.pointer);
    return target !== null && readText(target) === expected ? 0 : 1;
  }
  if (mode === "directory-membership") {
    mark(spec.target);
    try {
      const names = fs.readdirSync(spec.target.replace(/\/$/, "")).sort();
      return names.length === 1 && names[0] === "expected.txt" ? 0 : 1;
    } catch (_error) {
      return 1;
    }
  }
  if (mode === "missing-file") {
    mark(spec.target);
    return fs.existsSync(spec.target) ? 1 : 0;
  }
  if (mode === "child-process") {
    const completed = spawnSync(process.execPath, [__filename, "--child", spec.target, expected], {
      stdio: "inherit",
    });
    console.log("CLICK_BENCH_CHILD=1");
    return completed.status === null ? 1 : completed.status;
  }
  return 1;
}

process.exitCode = main();
