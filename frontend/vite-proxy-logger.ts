import fs from "fs";
import path from "path";
import type { ClientRequest, IncomingMessage, ServerResponse } from "http";
import type { ProxyErrorCallback } from "http-proxy";

const LOG_PATH = path.resolve(__dirname, "../data/dev-proxy-errors.log");
const DEDUPE_MS = 15_000;
const lastLogged = new Map<string, number>();
let backendHintShown = false;

function ensureLogDir(): void {
  fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
}

export function logProxyError(
  url: string | undefined,
  err: NodeJS.ErrnoException,
  options?: { toConsole?: boolean },
): void {
  const toConsole = options?.toConsole ?? false;
  const code = err.code ?? "ERROR";
  const key = `${code}:${url ?? ""}`;
  const now = Date.now();
  const prev = lastLogged.get(key) ?? 0;
  const repeat = prev > 0 && now - prev < DEDUPE_MS;

  if (now - prev >= DEDUPE_MS) {
    lastLogged.set(key, now);
    const line = `${new Date().toISOString()}\t${code}\t${url ?? "?"}\t${err.message}\n`;
    ensureLogDir();
    fs.appendFileSync(LOG_PATH, line, "utf8");
  }

  if (toConsole && !repeat) {
    console.warn(`[vite proxy → ${LOG_PATH}] ${url ?? "?"}: ${err.message}`);
  }

  if (code === "ECONNREFUSED" && !backendHintShown) {
    backendHintShown = true;
    const hint =
      `[vite] Backend not reachable at http://localhost:8000 — run: npm run dev:backend (from repo root)\n` +
      `[vite] Proxy errors are appended to ${LOG_PATH}\n`;
    ensureLogDir();
    fs.appendFileSync(LOG_PATH, `${new Date().toISOString()}\tHINT\t-\t${hint.replace(/\n/g, " ")}\n`, "utf8");
    console.warn(hint.trim());
  }
}

export function configureApiProxy(proxy: {
  on(event: "error", listener: ProxyErrorCallback): void;
}): void {
  proxy.on("error", (err: Error, req: IncomingMessage, res: ServerResponse | Socket) => {
    const nodeErr = err as NodeJS.ErrnoException;
    const url = (req as ClientRequest & { url?: string }).url;
    logProxyError(url, nodeErr, { toConsole: true });

    if (res && "writeHead" in res && !res.headersSent) {
      const body = JSON.stringify({
        error: "backend_unavailable",
        message: "API backend is not running on port 8000. Start it with: npm run dev:backend",
        detail: nodeErr.message,
        path: url,
      });
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(body);
    }
  });
}
