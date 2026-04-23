FROM python:3.11-slim

WORKDIR /app

# Install minimal build/runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install Python dependencies first (better cache usage)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf ~/.cache/pip

# Copy app source
COPY . .

# Install all-in-one startup script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN mkdir -p /app/data/temp_uploads && chmod -R 777 /app/data

ENV PYTHONUNBUFFERED=1

# FastAPI ingress port (can be overridden by GRAPH_RAG_PORT)
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]