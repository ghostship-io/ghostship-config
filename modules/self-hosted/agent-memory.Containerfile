# Pinned Basic Memory v1.0.0 plus the embedding model, so the service has no
# runtime egress. Build on the host and never pull this tag at runtime:
#
#   podman build -f modules/self-hosted/agent-memory.Containerfile \
#     -t localhost/agent-memory:1.0.0 modules/self-hosted
#
# The base is the official multi-arch OCI index for the v1.0.0 release tag
# (upstream commit c9bd187b83baba549d5cd16bacc180f8023d51c8).
ARG BASE=ghcr.io/basicmachines-co/basic-memory@sha256:cad49f5433bcd8592fea547907a2b967435b3fa60d0f81ebc4d558e2b5cb55a8
FROM ${BASE}

USER root

# The accepted-note path records file_write_status="synced" after the Markdown
# materializer returns. Upstream's atomic write does not fsync the file or its
# directory, so a power loss after that status can leave the source-of-truth
# file missing or stale and the next scan can delete or overwrite the accepted
# note. This patch fsyncs both before "synced" can be committed; startup
# recovery already replays pending/writing/failed rows from the accepted DB
# content.
COPY agent-memory-fsync.patch /tmp/agent-memory-fsync.patch
RUN apt-get update && \
    apt-get install -y --no-install-recommends patch && \
    patch -p1 -d /app < /tmp/agent-memory-fsync.patch && \
    rm -rf /var/lib/apt/lists/* /tmp/agent-memory-fsync.patch

ENV FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache
RUN mkdir -p "$FASTEMBED_CACHE_PATH" && \
    python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='$FASTEMBED_CACHE_PATH')" && \
    chown -R 3000:3000 /opt/agent-memory

# The NixOS module runs the container as 3000:3000, matching the private volume.
USER 3000:3000
