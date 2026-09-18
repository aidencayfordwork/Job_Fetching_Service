import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Vite rejects requests with an unrecognized Host header by default.
    // Lightning Studio's port-forwarding proxy rewrites it to a
    // per-studio *.cloudspaces.litng.ai subdomain, so the dev server
    // needs to explicitly allow that (any port, any studio on this
    // platform), or the proxy's every request gets blocked.
    allowedHosts: ['.cloudspaces.litng.ai'],
  },
})
