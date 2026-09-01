import type { NextConfig } from "next";

// The FastAPI backend. In dev it runs on :8000; override with KARAG_API_URL.
// Rewrites are resolved into the routes manifest at build time, so in Docker
// this has to arrive as a build arg — setting it at container start is too late.
const API = process.env.KARAG_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Emits .next/standalone with a self-contained server.js, so the runtime
  // image carries no node_modules.
  output: "standalone",
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${API}/v1/:path*` },
      { source: "/health", destination: `${API}/health` },
    ];
  },
};

export default nextConfig;
