// Overwritten at container start in production (see docker-entrypoint.sh).
// Local Vite uses relative /api paths via the proxy in vite.config.ts.
window.__RR_OPS_CONFIG__ = { apiBase: "" };
