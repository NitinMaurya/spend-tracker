import type { NextConfig } from "next";

/**
 * The six-tab layout collapsed to two destinations plus a Data utility.
 * These keep old bookmarks and links working rather than 404ing.
 */
const nextConfig: NextConfig = {
  // The engine binds to 127.0.0.1, so the app gets opened on that host as often
  // as on localhost. Without this, dev-only chunk requests 403 and client
  // components silently never hydrate.
  allowedDevOrigins: ["127.0.0.1"],

  async redirects() {
    return [
      { source: "/spending", destination: "/", permanent: false },
      { source: "/cards", destination: "/", permanent: false },
      { source: "/statements", destination: "/data", permanent: false },
      { source: "/review", destination: "/data", permanent: false },
      { source: "/evaluate", destination: "/plan", permanent: false },
    ];
  },
};

export default nextConfig;
