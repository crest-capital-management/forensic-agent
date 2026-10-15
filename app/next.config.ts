import type { NextConfig } from "next";

// The browser talks to /api/*; Next forwards it to the Python review API.
const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
  },
};

export default nextConfig;
