import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const bundledRuntimeLicenseBanner =
  "/*! Maru is Apache-2.0: see LICENSE.txt. Bundled dependency licenses: see THIRD_PARTY_NOTICES.md. */";
const preserveBundledRuntimeLicense: Plugin = {
  name: "maru:preserve-bundled-runtime-license",
  generateBundle(_options, bundle) {
    for (const output of Object.values(bundle)) {
      if (output.type === "chunk") {
        output.code = `${bundledRuntimeLicenseBanner}\n${output.code}`;
      }
    }
  }
};

export default defineConfig({
  plugins: [react(), preserveBundledRuntimeLicense],
  base: "/static/staff-console/",
  build: {
    outDir: "../../src/maru/core/static/staff-console",
    emptyOutDir: true,
    cssCodeSplit: false,
    license: {
      fileName: "THIRD_PARTY_NOTICES.md"
    },
    rollupOptions: {
      input: "src/main.tsx",
      output: {
        entryFileNames: "app.js",
        assetFileNames: (assetInfo) =>
          assetInfo.names.some((name) => name.endsWith(".css"))
            ? "app.css"
            : "assets/[name]-[hash][extname]",
        chunkFileNames: "assets/[name]-[hash].js"
      }
    }
  },
  server: {
    port: 5173,
    proxy: {
      "/accounts": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000"
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true
  }
});
