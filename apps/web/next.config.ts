import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typedRoutes: true,
  devIndicators: false,
  allowedDevOrigins: ["quantcn.wintrusttech.com", "aistockcn.com", "www.aistockcn.com"],
  // This panel is often run through the local Docker override, which uses `next dev`.
  // Keep infrequently visited routes like `/overview` warm longer so guest logins do not
  // trigger the transient full-page build overlay after a short idle period.
  onDemandEntries: {
    maxInactiveAge: 1000 * 60 * 60 * 24,
    pagesBufferLength: 10
  },
  async redirects() {
    return [
      { source: "/overview", destination: "/cn/overview", permanent: true },
      { source: "/research", destination: "/us/research", permanent: true },
      { source: "/data", destination: "/cn/quant?view=explorer", permanent: true },
      { source: "/picks", destination: "/cn/quant?view=signals", permanent: true },
      { source: "/paper", destination: "/cn/execution", permanent: true },
      { source: "/us/data", destination: "/us/quant?view=explorer", permanent: true },
      { source: "/us/picks", destination: "/us/quant?view=signals", permanent: true },
      { source: "/us/paper", destination: "/us/execution", permanent: true }
    ];
  }
};

export default nextConfig;
