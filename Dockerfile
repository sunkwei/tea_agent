# Tea Agent — Dockerfile
# Multi-stage build: slim production image
#
# Build:
#   docker build -t tea-agent .
#
# Run:
#   docker run -d --name tea-agent \
#     -v ~/.tea_agent:/root/.tea_agent \
#     -p 8081:8081 \
#     tea-agent

# ── Stage 1: Install dependencies ──
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY tea_agent/ tea_agent/

# Install core dependencies
RUN pip install --no-cache-dir -e ".[server]"

# ── Stage 2: Runtime ──
FROM python:3.11-slim

WORKDIR /app

# Runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/tea_agent/ tea_agent/
COPY --from=builder /app/pyproject.toml .

# Volume for config and data
VOLUME ["/root/.tea_agent"]

# Expose API port
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health')" || exit 1

# Default command: start server
CMD ["python", "-m", "tea_agent.server", "--host", "0.0.0.0", "--port", "8081"]
