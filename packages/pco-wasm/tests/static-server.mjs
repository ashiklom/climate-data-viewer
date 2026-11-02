// Minimal Range-capable static file server for tests (stands in for the Vite dev server / S3).
import { createServer } from "node:http";
import { createReadStream, statSync } from "node:fs";
import { join, normalize } from "node:path";

export function serveDirectory(root) {
  const server = createServer((req, res) => {
    const path = normalize(join(root, decodeURIComponent(new URL(req.url, "http://x").pathname)));
    if (!path.startsWith(root)) return res.writeHead(403).end();
    let size;
    try {
      size = statSync(path).size;
    } catch {
      return res.writeHead(404).end();
    }
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? "");
    if (!range) {
      res.writeHead(200, { "content-length": size });
      return createReadStream(path).pipe(res);
    }
    let start = range[1] === "" ? size - Number(range[2]) : Number(range[1]);
    let end = range[1] === "" || range[2] === "" ? size - 1 : Number(range[2]);
    end = Math.min(end, size - 1);
    res.writeHead(206, { "content-length": end - start + 1, "content-range": `bytes ${start}-${end}/${size}` });
    createReadStream(path, { start, end }).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port })));
}
