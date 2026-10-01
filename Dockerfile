# Deployment image for the Pharos API (FastAPI).
#
# This is the *other* shape from Dockerfile.ci. That file builds the environment
# only, so GitHub's actions/checkout can supply fresh source over it on every
# run. This one bundles environment AND code, so the container runs on its own —
# which is what a cloud host needs.
#
#   docker compose up          builds and runs this alongside the SPA
#   docker build -t pharos-api .   builds it alone
#
# Serves /api/* on port 8080, matching the run_command in .do/app.yaml so local
# behaviour and the App Platform deploy stay in step.

FROM python:3.11-slim

# System packages pip cannot express — and the reason Docker is worth it here.
# backend/vectordb/extract.py shells out to `pdftotext` (poppler-utils) and `textutil`.
# textutil is macOS-only: on any Linux host it isn't found and extraction
# silently yields "" rather than raising. Pinning the OS layer is how that class
# of "works on my Mac" bug stops being possible; requirements.txt cannot reach it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency manifests FIRST, install, and only then the source. Docker caches
# each instruction as a layer keyed on the files it read, so the expensive pip
# layer is reused on every build where no requirements file changed. Copying the
# source first would invalidate it on every edit and reinstall the world.
COPY requirements.txt ./
COPY backend/requirements.txt ./backend/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
         -r requirements.txt \
         -r backend/requirements.txt

# Now the code. Everything the API imports transitively, and the *_run.py entry
# points, so this same image can execute the scheduled jobs
# (`docker compose run --rm api python backend/forecast_run.py`). The build context is
# already narrowed by .dockerignore.
COPY . .

# Run as a non-root user. Nothing here needs root at runtime, and a container
# process that escapes its boundary should not land as uid 0 on the host kernel.
RUN useradd --create-home --uid 10001 pharos \
    && chown -R pharos:pharos /app
USER pharos

# PYTHONPATH exposes backend source packages and repo-root runtime files.
# PYTHONUNBUFFERED: without it Python block-buffers stdout when it is a pipe
# rather than a TTY, so logs arrive minutes late (or never, on a crash) in
# `docker logs` and in the platform log stream.
ENV PYTHONPATH=/app/backend:/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

EXPOSE 8080

# /api/health always returns HTTP 200 by design — a Supabase outage reports
# `status: degraded` in the body instead, because restart-looping the container
# would not fix the outage and would dump the warm cache. So this check is a
# genuine liveness probe: it fails only when the process is truly wedged.
# urllib, not curl, keeps the image free of an extra apt package.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else sys.exit(1)"

# Exec form, so uvicorn is PID 1 and receives SIGTERM directly. The shell form
# would fork it under /bin/sh, which does not forward signals — `docker stop`
# would then hang for its full 10s grace period and SIGKILL mid-request.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
