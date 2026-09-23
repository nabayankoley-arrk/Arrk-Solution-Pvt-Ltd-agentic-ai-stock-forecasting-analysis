/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: `npm run build` here produces frontend/out, which
  // backend/main.py mounts as StaticFiles at "/" (same origin as the API,
  // so no CORS configuration is needed in production).
  output: "export",
  images: { unoptimized: true },
};

module.exports = nextConfig;
