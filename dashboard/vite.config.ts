import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const NGROK_HEADER_PREFIX = "ngrok-auth";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.io", ".ngrok.app"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            for (const [key, value] of Object.entries(req.headers)) {
              if (
                key.toLowerCase().startsWith(NGROK_HEADER_PREFIX) &&
                typeof value === "string"
              ) {
                proxyReq.setHeader(key, value);
              }
            }
          });
        },
      },
    },
  },
});
