import { svelte } from "@sveltejs/vite-plugin-svelte";
import { createReadStream, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, normalize, resolve } from "node:path";
import { parse as parseToml } from "smol-toml";
import { defineConfig, type Plugin } from "vite";

const REPO = resolve(import.meta.dirname, "..");
const STORES = join(REPO, "data", "stores");

/**
 * Serve local Icechunk mirrors (data/stores/<name>.icechunk) at /data/<name>.icechunk with HTTP Range
 * support, as an S3-compatible host would. Paths in src/generated/sources.json point here in development;
 * swapping to object storage later only changes those URLs.
 */
function serveStores(): Plugin {
  return {
    name: "serve-local-stores",
    configureServer(server) {
      server.middlewares.use("/data", (req, res, next) => {
        const path = normalize(join(STORES, decodeURIComponent((req.url ?? "/").split("?")[0]!)));
        if (!path.startsWith(STORES)) return next();
        let size: number;
        try {
          const st = statSync(path);
          if (!st.isFile()) return next();
          size = st.size;
        } catch {
          res.statusCode = 404;
          return res.end();
        }
        res.setHeader("Accept-Ranges", "bytes");
        res.setHeader("Cache-Control", "no-cache");
        const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? "");
        if (!m) {
          res.setHeader("Content-Length", size);
          return createReadStream(path).pipe(res);
        }
        const start = m[1] === "" ? size - Number(m[2]) : Number(m[1]);
        const end = m[1] === "" || m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
        res.statusCode = 206;
        res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
        res.setHeader("Content-Length", end - start + 1);
        createReadStream(path, { start, end }).pipe(res);
      });
    },
  };
}

/**
 * Dev-only: POST /__snapshot?name=<name> with a PNG body saves it to data/logs/snapshots/<name>.png. Used to
 * verify WebGL rendering from automation, where page screenshots do not capture WebGL canvases.
 */
function snapshots(): Plugin {
  const dir = join(REPO, "data", "logs", "snapshots");
  return {
    name: "dev-snapshots",
    configureServer(server) {
      server.middlewares.use("/__snapshot", (req, res) => {
        const name = (new URL(req.url ?? "", "http://x").searchParams.get("name") ?? "snapshot").replace(/[^\w.-]/g, "_");
        const parts: Buffer[] = [];
        req.on("data", (d: Buffer) => parts.push(d));
        req.on("end", () => {
          mkdirSync(dir, { recursive: true });
          writeFileSync(join(dir, `${name}.png`), Buffer.concat(parts));
          res.end("ok");
        });
      });
    },
  };
}

/**
 * `virtual:cds-key` exports the local CDS API key (from ../_credentials.toml) for ERA5-Land ARCO reads.
 * Development only: a production build fails, so the key can never ship in a published bundle.
 * (If the site is published, replace with a user-supplied key.)
 */
function cdsKey(): Plugin {
  const id = "virtual:cds-key";
  let command: "serve" | "build" = "serve";
  return {
    name: "cds-key",
    configResolved(c) {
      command = c.command;
    },
    resolveId: (source) => (source === id ? "\0" + id : null),
    load(loadId) {
      if (loadId !== "\0" + id) return null;
      if (command === "build") {
        this.error("virtual:cds-key is development-only; refusing to bundle the CDS API key into a build");
      }
      const creds = parseToml(readFileSync(join(REPO, "_credentials.toml"), "utf8")) as Record<string, string>;
      return `export default ${JSON.stringify(creds["cds_api_key"] ?? "")};`;
    },
  };
}

export default defineConfig({
  plugins: [svelte(), serveStores(), cdsKey(), snapshots()],
  resolve: {
    // The linked pco-wasm package has its own dev copies; the codec must register into the app's zarrita.
    dedupe: ["zarrita", "icechunk-js"],
  },
  optimizeDeps: {
    // wasm-bindgen output locates its .wasm via import.meta.url; keep it out of pre-bundling.
    exclude: ["@climate-mirror/pco-wasm"],
  },
  // The linked pco-wasm package (and its .wasm) lives outside site/.
  server: { port: 5173, fs: { allow: [REPO] } },
});
