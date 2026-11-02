import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

// Unit tests run in Node with the app's resolution rules (notably resolve.dedupe of zarrita, so the
// linked pco-wasm package registers its codec into the same registry the app uses).
export default mergeConfig(viteConfig, defineConfig({ test: { include: ["src/**/*.test.ts"] } }));
