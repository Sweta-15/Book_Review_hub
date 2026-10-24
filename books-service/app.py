"""
books-service
=============
Microservice that owns the *book catalogue*.

REST API
--------
GET    /health            liveness  - is the process alive?
GET    /ready             readiness - can we reach MongoDB? (503 = "busy signal")
GET    /books[?q=text]    list books (optional case-insensitive title/author search)
POST   /books             create a book   {title, author, year?, description?}
GET    /books/<id>        fetch one book
DELETE /books/<id>        delete one book

Every response carries an `X-Served-By` header with the pod hostname so you
can SEE the Kubernetes load balancer spreading requests over the replicas.
"""
import logging
import os
import re
import socket
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import Flask, jsonify, request
from pymongo import MongoClient
from pymongo.errors import PyMongoError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [books-service] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "bookhub")
HOSTNAME = socket.gethostname()

app = Flask(__name__)

# MongoClient connects lazily, so the pod can start even if Mongo is not up yet.
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
books = client[DB_NAME]["books"]

try:
    books.create_index("title")
except PyMongoError as exc:  # Mongo not ready yet - not fatal
    log.warning("Could not create index yet: %s", exc)


def to_json(doc):
    """Convert a Mongo document to a JSON-friendly dict."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


def parse_id(book_id):
    try:
        return ObjectId(book_id)
    except (InvalidId, TypeError):
        return None


@app.after_request
def add_served_by(resp):
    resp.headers["X-Served-By"] = HOSTNAME
    return resp


@app.errorhandler(PyMongoError)
def db_error(exc):
    # Busy-signal pattern: tell the caller to retry later instead of crashing.
    log.error("Database error: %s", exc)
    return jsonify(error="database unavailable, please retry"), 503


@app.get("/health")
def health():
    return jsonify(status="ok", service="books-service", pod=HOSTNAME)


@app.get("/ready")
def ready():
    try:
        client.admin.command("ping")
        return jsonify(status="ready", pod=HOSTNAME)
    except PyMongoError as exc:
        return jsonify(status="not ready", error=str(exc)), 503


@app.get("/books")
def list_books():
    query = {}
    q = request.args.get("q", "").strip()
    if q:
        # re.escape prevents users from injecting their own regex patterns
        pattern = {"$regex": re.escape(q[:100]), "$options": "i"}
        query = {"$or": [{"title": pattern}, {"author": pattern}]}
    result = [to_json(b) for b in books.find(query).sort("created_at", -1).limit(500)]
    log.info("Listed %d books (q=%r)", len(result), q)
    return jsonify(books=result, count=len(result))


@app.post("/books")
def create_book():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    author = str(data.get("author", "")).strip()
    description = str(data.get("description", "")).strip()
    year = data.get("year")

    errors = []
    if not title or len(title) > 200:
        errors.append("title is required (max 200 characters)")
    if not author or len(author) > 200:
        errors.append("author is required (max 200 characters)")
    if len(description) > 2000:
        errors.append("description max 2000 characters")
    if year not in (None, ""):
        try:
            year = int(year)
            if not 0 <= year <= 2100:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("year must be a number between 0 and 2100")
    else:
        year = None
    if errors:
        return jsonify(errors=errors), 400

    doc = {
        "title": title,
        "author": author,
        "year": year,
        "description": description,
        "created_at": datetime.now(timezone.utc),
    }
    res = books.insert_one(doc)
    doc["_id"] = res.inserted_id
    log.info("Created book %s: %r by %r", res.inserted_id, title, author)
    return jsonify(to_json(doc)), 201


@app.get("/books/<book_id>")
def get_book(book_id):
    oid = parse_id(book_id)
    if oid is None:
        return jsonify(error="invalid book id"), 400
    doc = books.find_one({"_id": oid})
    if doc is None:
        return jsonify(error="book not found"), 404
    return jsonify(to_json(doc))


@app.delete("/books/<book_id>")
def delete_book(book_id):
    oid = parse_id(book_id)
    if oid is None:
        return jsonify(error="invalid book id"), 400
    res = books.delete_one({"_id": oid})
    if res.deleted_count == 0:
        return jsonify(error="book not found"), 404
    log.info("Deleted book %s", book_id)
    return "", 204


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=True)
