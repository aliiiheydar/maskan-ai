/** @type {import('next').NextConfig} */
const nextConfig = {
  // Traces the server and the modules it actually imports into
  // .next/standalone, which is what docker/frontend.Dockerfile copies into its
  // runtime stage: a few megabytes instead of shipping node_modules. No effect
  // on `next dev` or on a plain `next start` from a full checkout.
  output: "standalone",
};

export default nextConfig;
