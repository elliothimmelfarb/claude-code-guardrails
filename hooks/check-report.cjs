// Render an HTML report at desktop and phone width, save screenshots, and flag layout
// bugs a glance can miss: text squeezed to about one word per line, and sideways scroll.
//
// Command line: node check-report.cjs <report.html> [outDir]
//   exit 0 clean, 1 layout problems, 2 the check itself could not run.
// Hook (PostToolUse on Write|Edit): no arguments, reads the tool call from stdin.
//   exit 0 clean or skipped, 2 layout problems (Claude sees them), 1 could not run.
//
// Settings, all optional:
//   PLAYWRIGHT_PATH     where Playwright is, if require("playwright") cannot find it
//   CHECK_REPORT_MATCH  regex a file path must match in hook mode (default \.html?$)
//   CHECK_REPORT_WIDTHS name=pixels list (default desktop=1440,phone=390)
const fs = require("fs"), os = require("os"), path = require("path");
const { pathToFileURL } = require("url");

function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_PATH, "playwright",
    path.join(process.cwd(), "node_modules", "playwright")].filter(Boolean);
  for (const c of candidates) { try { return require(c); } catch {} }
  return null;
}

// Prefer Playwright's own Chromium, and fall back to an installed Chrome.
async function launch(pw) {
  try { return await pw.chromium.launch(); } catch { return pw.chromium.launch({ channel: "chrome" }); }
}

// Runs in the page. Lines are counted from where the text actually sits, because an
// element's height also includes its padding and any child blocks.
function findProblems() {
  const bad = [];
  const pageWidth = document.documentElement.scrollWidth;
  if (pageWidth > innerWidth + 1) bad.push(`page scrolls sideways (${pageWidth}px wide)`);
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest("svg")) continue;
    const nodes = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
    const own = nodes.map(n => n.textContent).join(" ").trim();
    const words = own.split(/\s+/).filter(Boolean).length;
    if (words < 4) continue;
    const tops = new Set();
    for (const node of nodes) {
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) if (rect.width) tops.add(Math.round(rect.top));
    }
    const lines = tops.size;
    if (lines >= 3 && words / lines < 2) bad.push(`squeezed text, ${words} words on ${lines} lines: "${own.slice(0, 60)}"`);
  }
  return bad;
}

async function check(file, outDir) {
  const pw = loadPlaywright();
  if (!pw) throw new Error("Playwright not found. Install it or set PLAYWRIGHT_PATH to its folder.");
  const widths = (process.env.CHECK_REPORT_WIDTHS || "desktop=1440,phone=390")
    .split(",").map(pair => pair.split("="));
  const browser = await launch(pw);
  const problems = [];
  try {
    for (const [name, width] of widths) {
      const page = await browser.newPage({ viewport: { width: Number(width), height: 900 } });
      await page.goto(pathToFileURL(file).href);
      await page.waitForTimeout(400);
      for (const found of await page.evaluate(findProblems)) problems.push(`[${name}] ${found}`);
      await page.screenshot({ path: path.join(outDir, `check-${name}.png`), fullPage: true });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  return problems;
}

async function main() {
  const hookMode = !process.argv[2];
  let file = process.argv[2], outDir = process.argv[3];
  if (hookMode) {
    file = JSON.parse(fs.readFileSync(0, "utf8")).tool_input?.file_path;
    const match = new RegExp(process.env.CHECK_REPORT_MATCH || "\\.html?$");
    if (!file || !match.test(file) || !fs.existsSync(file)) return 0;
    outDir = fs.mkdtempSync(path.join(os.tmpdir(), "check-report-"));
  }
  file = path.resolve(file);
  outDir = path.resolve(outDir || path.dirname(file));

  let problems;
  try {
    problems = await check(file, outDir);
  } catch (e) {
    console.error(`check-report could not run: ${e.message}`);
    return hookMode ? 1 : 2;
  }
  const say = hookMode ? console.error : console.log;
  for (const p of problems) say(p);
  say(problems.length
    ? `${problems.length} problem(s) in ${file}. Screenshots are in ${outDir}.`
    : `No layout problems found. Still look at the screenshots in ${outDir}.`);
  return problems.length ? (hookMode ? 2 : 1) : 0;
}

main().then(code => process.exit(code));
