#!/bin/sh
set -eu

# Vite bakes import.meta.env at build time; Cloud Run sets VITE_API_BASE at
# runtime. Write a small config the SPA reads before the bundle loads.
API_BASE="${VITE_API_BASE:-}"
API_BASE="${API_BASE%/}"

# Minimal JSON string escape (URLs only need \ and ").
ESCAPED=$(printf '%s' "$API_BASE" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')

cat > /usr/share/nginx/html/config.js <<EOF
window.__RR_OPS_CONFIG__ = { apiBase: "${ESCAPED}" };
EOF

exec nginx -g 'daemon off;'
