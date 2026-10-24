"""
frontend (API gateway + web UI)
===============================
The ONLY service exposed outside Kubernetes. It serves the web page and a
small REST API that the page calls. It never touches the database itself:
every request is fulfilled by calling the books-service and reviews-service
REST APIs (API Gateway / Backend-for-Frontend pattern).

REST API
--------
GET    /                          web user interface (HTML)
GET    /health                    liveness
GET    /api/catalog               all books merged with their rating summary
GET    /api/books/<id>            one book + its reviews
POST   /api/books                 add a book          -> books-service
POST   /api/books/<id>/reviews    add a review        -> reviews-service
DELETE /api/books/<id>            delete book + its reviews
"""
import logging
import os
import socket
import time

import requests
from flask import Flask, jsonify, render_template, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [frontend] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

BOOKS = os.environ.get("BOOKS_SERVICE_URL", "http://localhost:5001").rstrip("/")
REVIEWS = os.environ.get("REVIEWS_SERVICE_URL", "http://localhost:5002").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "3"))
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "2"))
HOSTNAME = socket.gethostname()

app = Flask(__name__)


class UpstreamUnavailable(Exception):
    def __init__(self, service, detail):
        super().__init__(detail)
        self.service = service
        self.detail = detail


def call(service, method, url, **kwargs):
    """REST call with timeout + retry. Retries on network errors and 503 busy signals."""
    last = "busy"
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
            if resp.status_code == 503 and attempt < HTTP_RETRIES:
                log.warning("%s busy (attempt %d), retrying", service, attempt)
                time.sleep(0.3 * attempt)
                continue
            log.info("%s %s -> %d (served by %s)", method, url, resp.status_code,
                     resp.headers.get("X-Served-By"))
            return resp
        except requests.RequestException as exc:
            last = str(exc)
            log.warning("%s call failed (attempt %d): %s", service, attempt, exc)
            time.sleep(0.3 * attempt)
    raise UpstreamUnavailable(service, last)


def relay(resp):
    """Pass an upstream response (status + JSON body) back to the browser."""
    if resp.status_code == 204 or not resp.content:
        return "", resp.status_code
    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text[:500]}
    return jsonify(body), resp.status_code


@app.errorhandler(UpstreamUnavailable)
def upstream_down(exc):
    return jsonify(error=f"{exc.service} is unavailable, please retry"), 503


@app.after_request
def add_served_by(resp):
    resp.headers["X-Served-By"] = HOSTNAME
    return resp


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(status="ok", service="frontend", pod=HOSTNAME)


@app.get("/api/catalog")
def catalog():
    b = call("books-service", "GET", f"{BOOKS}/books", params={"q": request.args.get("q", "")})
    if b.status_code != 200:
        return relay(b)
    books = b.json()["books"]

    # Graceful degradation: if reviews-service is down we still show the books.
    reviews_pod, reviews_ok, summary = None, True, {}
    try:
        r = call("reviews-service", "GET", f"{REVIEWS}/reviews/summary")
        reviews_pod = r.headers.get("X-Served-By")
        if r.status_code == 200:
            summary = r.json().get("summary", {})
        else:
            reviews_ok = False
    except UpstreamUnavailable:
        reviews_ok = False

    for book in books:
        s = summary.get(book["id"], {})
        book["avg_rating"] = s.get("avg_rating")
        book["review_count"] = s.get("count", 0)

    return jsonify(
        books=books,
        reviews_available=reviews_ok,
        served_by={
            "frontend": HOSTNAME,
            "books-service": b.headers.get("X-Served-By"),
            "reviews-service": reviews_pod,
        },
    )


@app.get("/api/books/<book_id>")
def book_detail(book_id):
    b = call("books-service", "GET", f"{BOOKS}/books/{book_id}")
    if b.status_code != 200:
        return relay(b)
    r = call("reviews-service", "GET", f"{REVIEWS}/reviews", params={"book_id": book_id})
    reviews = r.json().get("reviews", []) if r.status_code == 200 else []
    return jsonify(book=b.json(), reviews=reviews)


@app.post("/api/books")
def add_book():
    payload = request.get_json(silent=True) or {}
    return relay(call("books-service", "POST", f"{BOOKS}/books", json=payload))


@app.post("/api/books/<book_id>/reviews")
def add_review(book_id):
    payload = request.get_json(silent=True) or {}
    payload["book_id"] = book_id
    return relay(call("reviews-service", "POST", f"{REVIEWS}/reviews", json=payload))


@app.delete("/api/books/<book_id>")
def delete_book(book_id):
    call("reviews-service", "DELETE", f"{REVIEWS}/reviews/book/{book_id}")
    return relay(call("books-service", "DELETE", f"{BOOKS}/books/{book_id}"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
