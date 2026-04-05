/**
 * Single-page visit using Playwright Chromium — compact extraction, no raw HTML in response.
 */
import { chromium, type Browser, type Page } from "playwright";
import { mkdir, appendFile } from "fs/promises";
import { join } from "path";

export type VisitRequest = {
  identity_id?: string;
  thread_id?: string;
  run_id?: string;
  role_invocation_id?: string;
  graph_run_id?: string;
  url: string;
  source_kind?: string;
  snapshot?: boolean;
};

export type VisitResponse = {
  requested_url: string;
  resolved_url: string;
  status: "ok" | "error";
  http_status?: number;
  page_title?: string;
  meta_description?: string;
  discovered_links: string[];
  same_domain_links: string[];
  summary: string;
  traits?: { design_signals: string[]; tone_keywords: string[] };
  timing_ms: number;
  error?: string;
  snapshot_path?: string;
};

let _browser: Browser | null = null;

async function getBrowser(): Promise<Browser> {
  if (!_browser) {
    _browser = await chromium.launch({ headless: true });
  }
  return _browser;
}

function hostKey(u: string): string {
  try {
    return new URL(u).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "";
  }
}

function normalizeHref(href: string, base: string): string | null {
  try {
    const out = new URL(href, base).href;
    if (!out.startsWith("http://") && !out.startsWith("https://")) return null;
    return out.split("#")[0] ?? out;
  } catch {
    return null;
  }
}

function extractSignals(text: string, htmlSample: string): {
  design_signals: string[];
  tone_keywords: string[];
} {
  const design_signals: string[] = [];
  const lower = htmlSample.toLowerCase();
  const markers = ["grid", "flex", "hero", "animation", "parallax", "video", "carousel"];
  for (const m of markers) {
    if (lower.includes(m) && !design_signals.includes(m)) design_signals.push(m);
    if (design_signals.length >= 8) break;
  }
  const tone_keywords: string[] = [];
  const toneHints = ["minimal", "bold", "editorial", "playful", "luxury", "technical"];
  const tl = text.toLowerCase();
  for (const t of toneHints) {
    if (tl.includes(t) && !tone_keywords.includes(t)) tone_keywords.push(t);
    if (tone_keywords.length >= 6) break;
  }
  return { design_signals, tone_keywords };
}

async function appendLogLine(obj: Record<string, unknown>): Promise<void> {
  const root = process.env.KMBL_PLAYWRIGHT_LOG_DIR || ".kmbl";
  const line = JSON.stringify({ ts: new Date().toISOString(), ...obj }) + "\n";
  try {
    await mkdir(root, { recursive: true });
    await appendFile(join(root, "playwright_wrapper.log"), line, "utf8");
  } catch {
    /* best-effort */
  }
}

export async function visitPage(req: VisitRequest): Promise<VisitResponse> {
  const t0 = Date.now();
  const requested = req.url?.trim() || "";
  const baseErr = (msg: string): VisitResponse => ({
    requested_url: requested,
    resolved_url: requested,
    status: "error",
    discovered_links: [],
    same_domain_links: [],
    summary: "",
    timing_ms: Date.now() - t0,
    error: msg,
  });

  if (!requested.startsWith("http://") && !requested.startsWith("https://")) {
    return baseErr("invalid_url_scheme");
  }

  let page: Page | null = null;
  try {
    const browser = await getBrowser();
    page = await browser.newPage({
      userAgent:
        "Mozilla/5.0 (compatible; KMBL-PlaywrightWrapper/0.1; +https://kmbl.local)",
    });
    const navTimeout = Number(process.env.KMBL_PLAYWRIGHT_NAV_TIMEOUT_MS || 30000);
    const response = await page.goto(requested, {
      waitUntil: "domcontentloaded",
      timeout: navTimeout,
    });
    const httpStatus = response?.status() ?? undefined;
    const resolved = page.url();
    const title = (await page.title()) || "";

    const metaDesc =
      (await page
        .locator('meta[name="description"]')
        .getAttribute("content")
        .catch(() => null)) || "";

    const hrefs = await page.$$eval("a[href]", (els) =>
      els.map((a) => (a as HTMLAnchorElement).href).filter(Boolean),
    );
    const discovered = [...new Set(hrefs.map((h) => normalizeHref(h, resolved)).filter((x): x is string => !!x))];

    const originHost = hostKey(resolved);
    const sameDomain = discovered.filter((u) => hostKey(u) === originHost);

    let text = "";
    try {
      text = (await page.innerText("body", { timeout: 5000 })) || "";
    } catch {
      text = "";
    }
    const summary = text.replace(/\s+/g, " ").trim().slice(0, 400);
    const htmlSnippet = await page.content().then((h) => h.slice(0, 8000)).catch(() => "");
    const traits = extractSignals(text, htmlSnippet);

    let snapshot_path: string | undefined;
    if (req.snapshot) {
      const snapRoot =
        process.env.KMBL_PLAYWRIGHT_SNAPSHOT_DIR || join(".kmbl", "playwright_snapshots");
      const sub = req.run_id || req.graph_run_id || "adhoc";
      const dir = join(snapRoot, sub);
      await mkdir(dir, { recursive: true });
      const file = join(dir, `${Buffer.from(resolved).toString("base64url").slice(0, 80)}.html`);
      const html = await page.content();
      await appendFile(file, html, "utf8");
      snapshot_path = file;
    }

    const out: VisitResponse = {
      requested_url: requested,
      resolved_url: resolved,
      status: "ok",
      http_status: httpStatus,
      page_title: title.slice(0, 300),
      meta_description: metaDesc.slice(0, 500),
      discovered_links: discovered.slice(0, 200),
      same_domain_links: sameDomain.slice(0, 200),
      summary,
      traits,
      timing_ms: Date.now() - t0,
      snapshot_path,
    };
    await appendLogLine({ event: "visit_ok", requested, resolved: out.resolved_url });
    return out;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    await appendLogLine({ event: "visit_error", requested, error: msg });
    return {
      ...baseErr(msg.slice(0, 400)),
      timing_ms: Date.now() - t0,
    };
  } finally {
    if (page) await page.close().catch(() => {});
  }
}
