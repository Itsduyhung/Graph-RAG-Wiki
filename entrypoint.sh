#!/bin/bash
set -e

echo "=================================================="
echo "🚀 Graph-RAG-Wiki - All-in-One Container Startup"
echo "=================================================="

# Ensure local folders used by API/worker exist
mkdir -p /app/data/temp_uploads

echo ""
echo "🌐 Using external Redis from environment"
if [ -z "$REDIS_CONNECTION_STRING" ]; then
    echo "⚠️  REDIS_CONNECTION_STRING is not set - using REDIS_HOST:REDIS_PORT fallback"
else
    echo "✅ REDIS_CONNECTION_STRING is configured"
fi

echo ""
echo "👷 Starting Graph worker..."
cd /app
python worker.py > /proc/self/fd/1 2>&1 &
WORKER_PID=$!
echo "✅ Graph worker started (PID: $WORKER_PID)"

echo ""
echo "🌐 Starting Graph FastAPI server..."
cd /app
exec uvicorn fast_api_ingestion:app \
    --host 0.0.0.0 \
    --port ${GRAPH_RAG_PORT:-8000} \
    --log-level info