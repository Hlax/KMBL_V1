/**
 * Narrow HTTP interface for the KMBL Playwright wrapper (POST /visit, GET /health).
 */
import { createServer } from "http";
import { visitPage, type VisitRequest } from "./visitPage.js";

const PORT = Number(process.env.KMBL_PLAYWRIGHT_WRAPPER_PORT || 3847);

function readBody(req: import("http").IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c as Buffer));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, service: "kmbl-playwright-wrapper" }));
    return;
  }

  if (req.method === "POST" && req.url === "/visit") {
    try {
      const raw = await readBody(req);
      const body = JSON.parse(raw || "{}") as VisitRequest;
      if (!body.url) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "error", error: "missing url", requested_url: "", timing_ms: 0 }));
        return;
      }
      const out = await visitPage(body);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(out));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          requested_url: "",
          resolved_url: "",
          status: "error",
          discovered_links: [],
          same_domain_links: [],
          summary: "",
          timing_ms: 0,
          error: msg.slice(0, 400),
        }),
      );
    }
    return;
  }

  res.writeHead(404);
  res.end();
}).listen(PORT, "127.0.0.1", () => {
  console.error(`kmbl-playwright-wrapper listening on http://127.0.0.1:${PORT}`);
});
