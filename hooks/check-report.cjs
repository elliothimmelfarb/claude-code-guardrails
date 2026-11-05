// Render an HTML report at desktop and phone width, save screenshots, and flag layout
// bugs a glance can miss: text squeezed to about one word per line, and sideways scroll.
//
// Command line: node check-report.cjs <report.html> [outDir]
//   exit 0 clean, 1 layout problems, 2 the check itself could not run.
// Hook (PostToolUse on Write|Edit): no arguments, reads the tool call from stdin.
//   exit 0 clean or skipped, 2 layout problems (Claude sees them), 1 could not run.
//
// Settings, all optional:
//   PLAYWRIGHT_PATH     absolute path of Playwright's folder, if it is not installed next to
//                       this hook. Nothing else is searched, because code found through the
//                       current directory belongs to whichever repo is open, not to you.
//   CHECK_REPORT_MATCH  regex a file path must match in hook mode (default \.html?$)
//   CHECK_REPORT_WIDTHS name=pixels list (default desktop=1440,phone=390)
//
// The page is untrusted. Its scripts do not run, every request except the file itself is
// aborted, and only counts and fixed strings come back, so its text never reaches Claude.
const fs = require("fs"), os = require("os"), path = require("path");
const { pathToFileURL } = require("url");

const MAX_LINE = 300;

function loadPlaywright() {
  const configured = process.env.PLAYWRIGHT_PATH;
  const candidates = [path.join(__dirname, "node_modules", "playwright")];
  if (configured && path.isAbsolute(configured)) candidates.unshift(configured);
  for (const c of candidates) { try { return require(c); } catch {} }
  return null;
}

// Prefer Playwright's own Chromium, and fall back to an installed Chrome.
async function launch(pw) {
  try { return await pw.chromium.launch(); } catch { return pw.chromium.launch({ channel: "chrome" }); }
}

// Runs in the page. Lines are counted from where the text actually sits, because an
// element's height also includes its padding and any child blocks.
function measure() {
  let squeezed = 0, worstWords = 0, worstLines = 0;
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
    if (lines >= 3 && words / lines < 2) {
      squeezed++;
      if (lines > worstLines) { worstLines = lines; worstWords = words; }
    }
  }
  return { pageWidth: document.documentElement.scrollWidth, viewWidth: innerWidth, squeezed, worstWords, worstLines };
}

// Only numbers cross from the page, and only these fixed strings go out.
function problemsIn(m) {
  const n = (value) => Math.max(0, Math.min(Math.trunc(Number(value)) || 0, 1e7));
  const bad = [];
  if (n(m.pageWidth) > n(m.viewWidth) + 1) bad.push(`page scrolls sideways (${n(m.pageWidth)}px wide)`);
  if (n(m.squeezed)) {
    bad.push(`squeezed text in ${n(m.squeezed)} element(s), the worst has ${n(m.worstWords)} words on ${n(m.worstLines)} lines`);
  }
  return bad;
}

async function check(file, outDir) {
  const pw = loadPlaywright();
  if (!pw) throw new Error("Playwright not found. Install it next to this hook, or set PLAYWRIGHT_PATH to the absolute path of its folder.");
  const widths = (process.env.CHECK_REPORT_WIDTHS || "desktop=1440,phone=390")
    .split(",").map(pair => pair.split("="));
  const browser = await launch(pw);
  const problems = [];
  try {
    const url = pathToFileURL(file).href;
    for (const [name, width] of widths) {
      const context = await browser.newContext({
        viewport: { width: Number(width), height: 900 }, javaScriptEnabled: false, serviceWorkers: "block",
      });
      await context.route("**/*", route => (route.request().url() === url ? route.continue() : route.abort()));
      const page = await context.newPage();
      await page.goto(url);
      await page.waitForTimeout(400);
      for (const found of problemsIn(await page.evaluate(measure))) problems.push(`[${name}] ${found}`);
      await page.screenshot({ path: path.join(outDir, `check-${name}.png`), fullPage: true });
      await context.close();
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
    console.error(`check-report could not run: ${String(e.message).slice(0, MAX_LINE)}`);
    return hookMode ? 1 : 2;
  } finally {
    if (hookMode) fs.rmSync(outDir, { recursive: true, force: true });
  }
  const say = (line) => (hookMode ? console.error : console.log)(line.slice(0, MAX_LINE));
  for (const p of problems) say(p);
  const screenshots = hookMode ? "" : ` Screenshots are in ${outDir}.`;
  say(problems.length
    ? `${problems.length} problem(s) in ${file}.${screenshots}`
    : `No layout problems found.${screenshots}`);
  return problems.length ? (hookMode ? 2 : 1) : 0;
}

main().then(code => process.exit(code));
