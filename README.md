# Book Review Hub — a microservice application on Kubernetes

Book Review Hub is a small web application where users add books to a shared catalogue, write reviews and give 1–5 star ratings. It is built from **three independently scalable Python/Flask microservices** with REST APIs and a **MongoDB** database that keeps its data on persistent storage.

```
             browser
                │  HTTP (REST + HTML)
                ▼
   ┌───────────────────────────┐   LoadBalancer Service :8080 / NodePort 30080
   │ frontend  (gateway + UI)  │   ← only public entry point
   └──────┬──────────────┬─────┘
     REST │              │ REST
          ▼              ▼
 ┌────────────────┐  ┌─────────────────┐
 │ books-service  │◄─┤ reviews-service │   (reviews-service checks the book exists
 └───────┬────────┘  └────────┬────────┘    via the books-service REST API)
         │   MongoDB protocol │
         ▼                    ▼
     ┌──────────────────────────────┐
     │ MongoDB StatefulSet + PVC    │   ← persistent volume
     └──────────────────────────────┘
```

| Microservice | Port | Responsibility | REST API |
|---|---|---|---|
| `frontend` | 5000 | Web UI, API gateway; merges data from both back-ends | `GET /`, `GET /api/catalog`, `GET /api/books/<id>`, `POST /api/books`, `POST /api/books/<id>/reviews`, `DELETE /api/books/<id>`, `GET /health` |
| `books-service` | 5001 | Owns the book catalogue (`books` collection) | `GET /books[?q=]`, `POST /books`, `GET /books/<id>`, `DELETE /books/<id>`, `GET /health`, `GET /ready` |
| `reviews-service` | 5002 | Owns reviews and ratings (`reviews` collection) | `GET /reviews[?book_id=]`, `POST /reviews`, `GET /reviews/summary[/<id>]`, `DELETE /reviews/book/<id>`, `GET /health`, `GET /ready` |
| `mongo` | 27017 | Database (official `mongo:7` image) | — |

> **Pretend for scaling to make sense:** the app is tiny and a single pod could serve it all. Imagine a popular reading community (think thousands of readers per minute at peak, e.g. when a book club publishes its monthly pick). Browsing the catalogue is far more common than writing reviews, so `books-service` and `frontend` need more replicas than `reviews-service` — which is why each service scales on its own.

## Repository layout

```
frontend/          Flask gateway + templates/index.html  (Dockerfile)
books-service/     Flask REST API for books              (Dockerfile)
reviews-service/   Flask REST API for reviews            (Dockerfile)
mongo-init/        DB init script for docker compose
docker-compose.yml local development (bind mounts + hot reload)
k8s/
  00-namespace.yaml        namespace (separate so data survives app teardown)
  10-mongodb.yaml          MongoDB StatefulSet, headless Service, PVC templates, init ConfigMap
  20-services.yaml         ConfigMap + 3 Deployments + 3 Services
  30-autoscaling.yaml      (optional) HorizontalPodAutoscalers
  40-network-policy.yaml   (optional) NetworkPolicies
scripts/           set-dockerhub-user, build-and-push, deploy, cleanup, logs
```

## Step 1 — Run locally with Docker Compose (development)

```bash
docker compose up --build
# open http://localhost:8080
docker compose up -d --scale books-service=3     # try scaling locally
docker compose down          # add -v to also delete the local data volume
```

## Step 2 — Build and push the images to Docker Hub

```bash
docker login
./scripts/build-and-push.sh <your-dockerhub-username>
./scripts/set-dockerhub-user.sh <your-dockerhub-username>   # writes your username into k8s/20-services.yaml
```

## Step 3 — Start Kubernetes

**minikube (Linux/any):**
```bash
minikube start                       # or: minikube start --cni=calico   (to enforce NetworkPolicies)
minikube addons enable metrics-server   # optional, for autoscaling
```
**Docker Desktop (Windows/Mac):** Settings → Kubernetes → Enable Kubernetes.

## Step 4 — Deploy

```bash
./scripts/deploy.sh                  # NETWORK_POLICY=1 ./scripts/deploy.sh  to also apply network policies
```
The script creates the namespace, generates random database passwords into a Kubernetes **Secret**, starts MongoDB, waits until it is ready, then starts the three microservices.

Open the app:
* minikube: `minikube service frontend -n bookhub`
* Docker Desktop: <http://localhost:8080>

## Step 5 — Things to show (demo commands)

```bash
kubectl -n bookhub get all,pvc                                   # what is running
./scripts/logs.sh frontend                                       # follow logs of all frontend replicas
./scripts/logs.sh books-service

# Independent horizontal scaling
kubectl -n bookhub scale deployment/books-service --replicas=4
kubectl -n bookhub scale deployment/reviews-service --replicas=1
kubectl -n bookhub get pods -o wide
# (if the autoscaler is installed, it will move replicas back within its min/max)

# Call a REST API directly from inside the cluster
kubectl -n bookhub run curl --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://books-service:5001/books

# Persistence: delete the database pod -> it comes back with the same data
kubectl -n bookhub delete pod mongo-0
# Persistence across a full teardown / cluster restart
./scripts/cleanup.sh && ./scripts/deploy.sh
minikube stop && minikube start
```

The page footer shows which **pod** served each request (`X-Served-By` header). Refresh a few times to see the load balancing across replicas.

Generate load to watch the autoscaler (needs metrics-server):
```bash
kubectl -n bookhub run load --rm -it --image=busybox --restart=Never -- \
  sh -c 'while true; do wget -q -O- http://frontend:8080/api/catalog >/dev/null; done'
kubectl -n bookhub get hpa -w
```

## Step 6 — Clean up

```bash
./scripts/cleanup.sh          # remove the app, keep the data
./scripts/cleanup.sh purge    # remove everything incl. the database volumes
```

## REST API examples

```bash
curl -X POST http://localhost:8080/api/books -H 'Content-Type: application/json' \
     -d '{"title":"War and Peace","author":"Leo Tolstoy","year":1869}'
curl http://localhost:8080/api/catalog
curl -X POST http://localhost:8080/api/books/<id>/reviews -H 'Content-Type: application/json' \
     -d '{"reviewer":"Anna","rating":5,"comment":"Long but worth it"}'
```
