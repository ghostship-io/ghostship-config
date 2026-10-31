# Optimized Basic Memory v1.0.0 packaging: one Python interpreter, no dev
# dependency group, no post-install recursive chown copy-up, and a non-editable
# install so the final image carries only the venv plus the pre-baked model.
ARG PYTHON=docker.io/library/python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f

FROM ${PYTHON} AS build
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /bin/
WORKDIR /app
RUN curl -fsSL 'https://github.com/basicmachines-co/basic-memory/archive/c9bd187b83baba549d5cd16bacc180f8023d51c8.tar.gz' -o /tmp/basic-memory.tar.gz && \
    tar -xzf /tmp/basic-memory.tar.gz -C /app --strip-components=1 && \
    rm /tmp/basic-memory.tar.gz

COPY agent-memory-fsync-patch.py /tmp/agent-memory-fsync-patch.py
COPY agent-memory-fsync-test.py /tmp/agent-memory-fsync-test.py
RUN AGENT_MEMORY_FILE_UTILS=/app/src/basic_memory/file_utils.py python /tmp/agent-memory-fsync-patch.py
RUN uv sync --no-dev --frozen --no-editable --python /usr/local/bin/python && \
    /app/.venv/bin/python /tmp/agent-memory-fsync-test.py && \
    rm -f /tmp/agent-memory-fsync-patch.py /tmp/agent-memory-fsync-test.py

ENV FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache
RUN mkdir -p "$FASTEMBED_CACHE_PATH" && \
    /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='$FASTEMBED_CACHE_PATH')" && \
    chown -R 3000:3000 /opt/agent-memory

FROM ${PYTHON}
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
    BASIC_MEMORY_CONFIG_DIR=/data/config \
    BASIC_MEMORY_HOME=/data/projects/.main \
    BASIC_MEMORY_PROJECT_ROOT=/data/projects
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /opt/agent-memory /opt/agent-memory
USER 3000:3000
