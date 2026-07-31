import type { NextConfig } from "next";

// The FastAPI backend. In dev it runs on :8000; override with KARAG_API_URL.
const API = process.env.KARAG_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${API}/v1/:path*` },
      { source: "/health", destination: `${API}/health` },
    ];
  },
};

export default nextConfig;
