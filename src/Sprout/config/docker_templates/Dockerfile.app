# Runner image for the Docker six-lane stack (see docker-compose.yml).
#
# The build context is this directory only: `requirements-lanes.txt` is a
# `uv export` of the lock file (core dependencies plus the `lanes` extra:
# redis / pymilvus / neo4j, and the pytest dev group). The project source is
# deliberately *not* copied — it arrives as a read-only bind mount at /app, so
# the image stays a thin runner and code changes never require a rebuild.

FROM python:3.13-slim

# PyPI is unreachable often enough from CN networks that the mirror is the
# default; override with --build-arg PIP_INDEX_URL=... for a plain PyPI run.
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    SPROUT_CONFIG=/app/docker/sprout.containers.toml

COPY requirements-lanes.txt /tmp/requirements-lanes.txt
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
        -r /tmp/requirements-lanes.txt \
    && rm -f /tmp/requirements-lanes.txt

# /data is the volume holding the file authorities (SQLite, JSONL, BlobStore);
# the relative DSNs in sprout.containers.toml resolve against it.
WORKDIR /data

# Six lanes, one container: writes through the production storage bundle and
# reads every lane back with its own client. That is `sprout storage check`
# (Sprout/storage/lanediag.py); the package is not installed here, so the CLI is
# reached as a module over PYTHONPATH.
CMD ["python", "-m", "Sprout", "storage", "check"]
