"""
reviews-service
===============
Microservice that owns *reviews and ratings*.

It is also a REST *client*: before saving a review it calls the
books-service REST API (GET /books/<id>) to check that the book exists.

REST API
--------
GET    /health                      liveness
GET    /ready                       readiness (503 if MongoDB is unreachable)
GET    /reviews?book_id=<id>        list reviews (optionally for one book)
POST   /reviews                     create {book_id, reviewer, rating 1-5, comment?}
GET    /reviews/summary             average rating + count for every book
GET    /reviews/summary/<book_id>   average rating + count for one book
DELETE /reviews/book/<book_id>      delete all reviews of a book
"""
import logging
import os
import socket
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request
from pymongo import MongoClient
from pymongo.errors import PyMongoError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [reviews-service] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "bookhub")
BOOKS_SERVICE_URL = os.environ.get("BOOKS_SERVICE_URL", "http://localhost:5001").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "3"))
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "2"))
HOSTNAME = socket.gethostname()

app = Flask(__name__)

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
reviews = client[DB_NAME]["reviews"]

try:
    reviews.create_index("book_id")
except PyMongoError as exc:
    log.warning("Could not create index yet: %s", exc)


class UpstreamUnavailable(Exception):
    pass


def call_books_service(path):
    """GET a path on books-service with a timeout and retry (node-failure pattern)."""
    url = f"{BOOKS_SERVICE_URL}{path}"
    last_error = "busy"
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT)
            if resp.status_code == 503 and attempt < HTTP_RETRIES:
                log.warning("books-service busy (attempt %d), retrying", attempt)
                time.sleep(0.3 * attempt)
                continue
            log.info("GET %s -> %d (served by %s)", url, resp.status_code,
                     resp.headers.get("X-Served-By"))
            return resp
        except requests.RequestException as exc:
            last_error = str(exc)
            log.warning("books-service call failed (attempt %d): %s", attempt, exc)
            time.sleep(0.3 * attempt)
    raise UpstreamUnavailable(last_error)


def to_json(doc):
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


@app.after_request
def add_served_by(resp):
    resp.headers["X-Served-By"] = HOSTNAME
    return resp


@app.errorhandler(PyMongoError)
def db_error(exc):
    log.error("Database error: %s", exc)
    return jsonify(error="database unavailable, please retry"), 503


@app.get("/health")
def health():
    return jsonify(status="ok", service="reviews-service", pod=HOSTNAME)


@app.get("/ready")
def ready():
    try:
        client.admin.command("ping")
        return jsonify(status="ready", pod=HOSTNAME)
    except PyMongoError as exc:
        return jsonify(status="not ready", error=str(exc)), 503


@app.get("/reviews")
def list_reviews():
    query = {}
    book_id = request.args.get("book_id", "").strip()
    if book_id:
        query["book_id"] = book_id
    result = [to_json(r) for r in reviews.find(query).sort("created_at", -1).limit(500)]
    return jsonify(reviews=result, count=len(result))


@app.post("/reviews")
def create_review():
    data = request.get_json(silent=True) or {}
    book_id = str(data.get("book_id", "")).strip()
    reviewer = str(data.get("reviewer", "")).strip()
    comment = str(data.get("comment", "")).strip()
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        rating = None

    errors = []
    if not book_id:
        errors.append("book_id is required")
    if not reviewer or len(reviewer) > 100:
        errors.append("reviewer is required (max 100 characters)")
    if rating is None or not 1 <= rating <= 5:
        errors.append("rating must be a whole number from 1 to 5")
    if len(comment) > 2000:
        errors.append("comment max 2000 characters")
    if errors:
        return jsonify(errors=errors), 400

    # Service-to-service REST call: does the book exist?
    try:
        resp = call_books_service(f"/books/{book_id}")
    except UpstreamUnavailable as exc:
        return jsonify(error="books-service unavailable, please retry", detail=str(exc)), 503
    if resp.status_code in (400, 404):
        return jsonify(error="book does not exist"), 400
    if resp.status_code != 200:
        return jsonify(error=f"books-service returned {resp.status_code}"), 502

    doc = {
        "book_id": book_id,
        "reviewer": reviewer,
        "rating": rating,
        "comment": comment,
        "created_at": datetime.now(timezone.utc),
    }
    res = reviews.insert_one(doc)
    doc["_id"] = res.inserted_id
    log.info("Review %s saved for book %s (rating %d)", res.inserted_id, book_id, rating)
    return jsonify(to_json(doc)), 201


def summarise(match=None):
    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline.append({"$group": {
        "_id": "$book_id",
        "avg_rating": {"$avg": "$rating"},
        "count": {"$sum": 1},
    }})
    return {
        row["_id"]: {"avg_rating": round(row["avg_rating"], 1), "count": row["count"]}
        for row in reviews.aggregate(pipeline)
    }


@app.get("/reviews/summary")
def summary_all():
    return jsonify(summary=summarise())


@app.get("/reviews/summary/<book_id>")
def summary_one(book_id):
    s = summarise({"book_id": book_id}).get(book_id, {"avg_rating": None, "count": 0})
    return jsonify(book_id=book_id, **s)


@app.delete("/reviews/book/<book_id>")
def delete_for_book(book_id):
    res = reviews.delete_many({"book_id": book_id})
    log.info("Deleted %d reviews for book %s", res.deleted_count, book_id)
    return jsonify(deleted=res.deleted_count)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)), debug=True)
