// Run: node --test tests/*.test.cjs
// Needs Playwright (npm ci) and a browser (Chrome, or npx playwright install chromium).
const test = require("node:test"), assert = require("node:assert");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");

const HOOK = path.join(__dirname, "..", "hooks", "check-report.cjs");
const fixture = (name) => path.join(__dirname, "fixtures", name);

function cli(file) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "check-report-"));
  return spawnSync("node", [HOOK, file, out], { encoding: "utf8" });
}
function hook(filePath, env = {}) {
  return spawnSync("node", [HOOK], {
    encoding: "utf8", env: { ...process.env, ...env },
    input: JSON.stringify({ tool_input: { file_path: filePath } }),
  });
}

test("a clean page passes and leaves screenshots", () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "check-report-"));
  const r = spawnSync("node", [HOOK, fixture("ok.html"), out], { encoding: "utf8" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.ok(fs.existsSync(path.join(out, "check-phone.png")));
});

test("fails on sideways scroll at phone width only", () => {
  const r = cli(fixture("sideways.html"));
  assert.equal(r.status, 1, r.stdout + r.stderr);
  assert.match(r.stdout, /\[phone\] page scrolls sideways/);
  assert.doesNotMatch(r.stdout, /\[desktop\]/);
});

test("fails on text squeezed to about one word per line", () => {
  const r = cli(fixture("squeezed.html"));
  assert.equal(r.status, 1, r.stdout + r.stderr);
  assert.match(r.stdout, /\[phone\] squeezed text/);
});

test("short text in a heavily padded box is not squeezed", () => {
  const r = cli(fixture("padded.html"));
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("a path with a space and a hash loads", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "check report #1-"));
  const copy = path.join(dir, "sideways.html");
  fs.copyFileSync(fixture("sideways.html"), copy);
  assert.equal(cli(copy).status, 1);
});

test("hook mode reports problems on stderr with exit 2", () => {
  const r = hook(fixture("sideways.html"));
  assert.equal(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stderr, /page scrolls sideways/);
});

test("hook mode skips files the match pattern excludes", () => {
  assert.equal(hook(fixture("sideways.html"), { CHECK_REPORT_MATCH: "/reports/" }).status, 0);
  assert.equal(hook("/tmp/notes.md").status, 0);
});

test("widths are configurable", () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "check-report-"));
  const r = spawnSync("node", [HOOK, fixture("sideways.html"), out], {
    encoding: "utf8", env: { ...process.env, CHECK_REPORT_WIDTHS: "wide=1000" },
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("a missing browser library is a tool error, not a failed report", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "check-report-"));
  const copy = path.join(dir, "check-report.cjs");
  fs.copyFileSync(HOOK, copy);
  const r = spawnSync("node", [copy, fixture("ok.html")], { encoding: "utf8", cwd: dir });
  assert.equal(r.status, 2, r.stdout + r.stderr);
  assert.match(r.stderr, /Playwright not found/);
});
