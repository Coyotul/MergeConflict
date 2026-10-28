import type { NextConfig } from "next";

const config: NextConfig = {
  transpilePackages: ["@banking/demo", "@banking/ui"],
  poweredByHeader: false,
};
export default config;
