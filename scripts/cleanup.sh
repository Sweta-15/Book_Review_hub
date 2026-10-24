#!/usr/bin/env bash
# Usage:
#   ./scripts/cleanup.sh          remove the app but KEEP the data (PVCs + Secret)
#   ./scripts/cleanup.sh purge    remove EVERYTHING including the stored data
set -euo pipefail
cd "$(dirname "$0")/.."
NS=bookhub

if [ "${1:-}" = "purge" ]; then
  kubectl delete namespace "$NS" --ignore-not-found --wait=true
  echo "Everything removed, including the database volumes."
else
  kubectl delete --ignore-not-found \
    -f k8s/40-network-policy.yaml -f k8s/30-autoscaling.yaml \
    -f k8s/20-services.yaml -f k8s/10-mongodb.yaml
  echo "App removed. Data kept:"
  kubectl -n "$NS" get pvc
  echo "Run ./scripts/deploy.sh again and your books and reviews will still be there."
fi
