/// <reference types="vitest/config" />
import { createReadStream, existsSync } from "node:fs";
import { resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

const ROOT = fileURLToPath(new URL(".", import.meta.url));
const MAPLIBRE_DEV_WORKER_PREFIX = "/vendor/maplibre";

/**
 * Dev only: serve MapLibre's worker modules byte-for-byte. Vite's transform injects `/@vite/client`
 * into them, which cannot run inside a Worker, so the map never finishes loading its style.
 * The production build instead bundles the worker via `?worker&url` (see src/map/MapView.tsx).
 */
function maplibreDevWorker(): Plugin {
  const dist = resolve(ROOT, "node_modules/maplibre-gl/dist");
  return {
    name: "opsmap:maplibre-dev-worker",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use(MAPLIBRE_DEV_WORKER_PREFIX, (req, res, next) => {
        const file = resolve(dist, `.${(req.url ?? "").split("?")[0]}`);
        if (!file.startsWith(dist + sep) || !file.endsWith(".mjs") || !existsSync(file)) return next();
        res.setHeader("Content-Type", "text/javascript");
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.OPSMAP_API_TARGET || "http://127.0.0.1:8000";
  const proxy = {
    // the UI always calls /api/...; Vite forwards to FastAPI, so no CORS setup is needed
    "/api": { target: apiTarget, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, "") },
  };
  return {
    plugins: [react(), maplibreDevWorker()],
    server: { port: 5173, proxy },
    preview: { proxy },
    worker: { format: "es" },
    build: {
      target: "es2022",
      chunkSizeWarningLimit: 1200,
      rolldownOptions: {
        output: {
          // long-lived vendor chunks: the app chunk changes, the map engines rarely do
          advancedChunks: {
            groups: [
              { name: "maplibre", test: /node_modules[\\/]maplibre-gl/ },
              { name: "deck", test: /node_modules[\\/](@deck\.gl|@luma\.gl|@math\.gl|@loaders\.gl|@probe\.gl)/ },
            ],
          },
        },
      },
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.ts"],
      coverage: { include: ["src/lib/**", "src/api/**", "src/state/**"] },
    },
  };
});
