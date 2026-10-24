#!/usr/bin/env bash
# Follow the logs of ALL replicas of one service (handy for the video).
# Usage: ./scripts/logs.sh frontend|books-service|reviews-service|mongo
set -euo pipefail
APP="${1:?Usage: $0 frontend|books-service|reviews-service|mongo}"
kubectl -n bookhub logs -f -l "app=${APP}" --prefix --max-log-requests 10 --tail 20
