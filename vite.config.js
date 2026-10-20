import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      deny: [
        ".env",
        ".env.*",
        "**/.git/**",
        "**/.venv/**",
        "**/data/**",
        "**/local-backups/**",
        "**/archives/**",
        "**/.openai/**",
        "**/output/**",
      ],
    },
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
