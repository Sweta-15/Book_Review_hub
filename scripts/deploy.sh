#!/usr/bin/env bash
# Deploy Book Review Hub to the current Kubernetes context (minikube or Docker Desktop).
# Usage: ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
NS=bookhub

if grep -q "YOUR_DOCKERHUB_USER" k8s/20-services.yaml; then
  echo "ERROR: run ./scripts/set-dockerhub-user.sh <your-dockerhub-username> first." >&2
  exit 1
fi

echo "==> 1/5 Namespace"
kubectl apply -f k8s/00-namespace.yaml

echo "==> 2/5 Secret (generated once, never stored in git)"
if kubectl -n "$NS" get secret bookhub-secrets >/dev/null 2>&1; then
  echo "    bookhub-secrets already exists - keeping it (the database user was created with it)."
else
  ROOT_PW="$(openssl rand -hex 16)"
  APP_PW="$(openssl rand -hex 16)"
  kubectl -n "$NS" create secret generic bookhub-secrets \
    --from-literal=mongo-root-username=root \
    --from-literal=mongo-root-password="$ROOT_PW" \
    --from-literal=app-db-user=bookhub_app \
    --from-literal=app-db-password="$APP_PW" \
    --from-literal=mongo-uri="mongodb://bookhub_app:${APP_PW}@mongo-0.mongo:27017/bookhub?authSource=bookhub"
fi

echo "==> 3/5 MongoDB (StatefulSet + persistent volume)"
kubectl apply -f k8s/10-mongodb.yaml
kubectl -n "$NS" rollout status statefulset/mongo --timeout=300s

echo "==> 4/5 Microservices"
kubectl apply -f k8s/20-services.yaml
for d in books-service reviews-service frontend; do
  kubectl -n "$NS" rollout status "deployment/$d" --timeout=300s
done

echo "==> 5/5 Optional extras"
if kubectl get apiservices v1beta1.metrics.k8s.io >/dev/null 2>&1; then
  kubectl apply -f k8s/30-autoscaling.yaml
else
  echo "    metrics-server not found - skipping autoscaling (minikube addons enable metrics-server)"
fi
if [ "${NETWORK_POLICY:-0}" = "1" ]; then
  kubectl apply -f k8s/40-network-policy.yaml
fi

echo
kubectl -n "$NS" get pods,svc,pvc
echo
if command -v minikube >/dev/null 2>&1 && minikube status >/dev/null 2>&1; then
  echo "Open the app with:  minikube service frontend -n $NS"
else
  echo "Open the app at:    http://localhost:8080   (Docker Desktop)"
fi
