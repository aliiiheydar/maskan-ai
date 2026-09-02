# syntax=docker/dockerfile:1
#
# The FastAPI backend. One stage: the dependencies are all manylinux wheels
# (numpy, scikit-learn, shapely, h3), so nothing is compiled here and there is
# no build stage worth throwing away.
#
# Built from the repository root, not from backend/ -- see the compose files.
# The build context has to reach `backend/`, and .dockerignore is what keeps
# the 250 MB of crawl output and local databases beside it out of the context.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements before the source, so editing a Python file does not reinstall
# scikit-learn. This layer changes only when requirements.txt does.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# The corpus is written at runtime (see app.main -- the shipped seed is
# unpacked on the first start), and it belongs on a volume rather than in a
# layer: 114 MB that would otherwise be rebuilt into every image, and lost on
# every deploy. DB_PATH points the app at it; the compose files mount it.
ENV DB_PATH=/data/maskan.db
RUN useradd --create-home --uid 10001 maskan \
    && mkdir -p /data \
    && chown -R maskan:maskan /app /data
USER maskan

EXPOSE 8000

# Up is not the question -- a backend that failed to unpack the corpus serves
# every request perfectly and returns the wrong city. /health reports the row
# count it is actually serving. The start period covers the one-off unpack of
# the shipped seed, which takes a few seconds on a first boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys;\
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
