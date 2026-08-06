/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  // Allow opening the NOC via http://127.0.0.1:3000 (HMR /_next otherwise blocked).
  allowedDevOrigins: ['127.0.0.1', 'localhost', '192.168.0.157'],
}

export default nextConfig
