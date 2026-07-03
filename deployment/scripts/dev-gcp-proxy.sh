#!/usr/bin/env bash
# Start local dev environment proxied to GCP Cloud Run services.
#
# Usage:  ./deployment/scripts/dev-gcp-proxy.sh
# Stop:   Ctrl-C (kills all background processes)
#
# What this does:
#   1. Proxies the Cloud Run orchestrator to localhost:8080
#   2. Starts the Vite web dev server at localhost:5173 (pointed at the proxy)
#   3. Optionally proxies the ops-web Cloud Run service at localhost:8081
#
# Prerequisites:
#   - gcloud authenticated: gcloud auth login
#   - cloud-run-proxy installed: gcloud components install cloud-run-proxy
#   - web deps installed: cd web && npm install
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="robo-reliance-ops"
REGION="us-central1"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill 0 2>/dev/null
  wait 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

echo "==> Proxying orchestrator API to http://localhost:8080"
gcloud run services proxy inner-loop-orchestrator \
  --region "$REGION" --project "$PROJECT" --port=8080 &
sleep 2

echo "==> Starting web app dev server at http://localhost:5173"
cd "$ROOT_DIR/web"
VITE_API_BASE=http://localhost:8080 npm run dev &
sleep 1

echo ""
echo "============================================"
echo "  GCP Dev Environment Ready"
echo "============================================"
echo ""
echo "  Web App:        http://localhost:5173"
echo "  Orchestrator:   http://localhost:8080"
echo "  Swagger Docs:   http://localhost:8080/docs"
echo "  Health Check:   http://localhost:8080/health"
echo ""
echo "  Press Ctrl-C to stop all services."
echo "============================================"
echo ""

wait
