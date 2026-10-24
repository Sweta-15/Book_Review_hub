# ---- reviews-service ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5002

WORKDIR /app

# Install dependencies first so this layer is cached between code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Security: never run as root inside the container
RUN useradd --create-home --uid 10001 appuser
USER 10001

EXPOSE 5002

# gunicorn = production WSGI server (Flask's built-in server is for development only)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 2 --worker-tmp-dir /dev/shm --access-logfile - app:app"]
