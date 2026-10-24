#!/usr/bin/env bash
# One-time setup: put YOUR Docker Hub username into the Kubernetes YAML.
# Usage: ./scripts/set-dockerhub-user.sh <dockerhub-username>
set -euo pipefail
cd "$(dirname "$0")/.."
USER_NAME="${1:?Usage: $0 <dockerhub-username>}"
sed -i.bak "s#YOUR_DOCKERHUB_USER/#${USER_NAME}/#g" k8s/20-services.yaml && rm -f k8s/20-services.yaml.bak
grep -n "image:" k8s/20-services.yaml
