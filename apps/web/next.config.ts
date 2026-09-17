import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Requis par apps/web/Dockerfile : produit .next/standalone (serveur Node
  // minimal sans node_modules complet) pour une image de runtime légère.
  output: "standalone",
};

export default nextConfig;