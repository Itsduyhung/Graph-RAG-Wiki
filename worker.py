"""
Background worker for Graph-RAG ingestion.

This worker consumes jobs from Redis (compatible with Wiki Backend queue payload),
extracts entities/relationships from uploaded content, and persists them to Neo4j
using the same extraction flow as FastAPI /upload.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

import redis
import requests
from dotenv import load_dotenv

from graph.storage import GraphDB
from pipeline.custom_graph_extractor import CustomGraphExtractor


def _load_environment() -> None:
    base_dir = Path(__file__).resolve().parent

    # Primary Graph-RAG-Wiki env files
    load_dotenv(base_dir / ".env", override=False)
    load_dotenv(base_dir / "config" / "secrets.env", override=False)


_load_environment()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("GraphRagWorker")


TASK_STATUS_PENDING = "PENDING"
TASK_STATUS_PROCESSING = "PROCESSING"
TASK_STATUS_COMPLETED = "COMPLETED"
TASK_STATUS_FAILED = "FAILED"


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _create_redis_client(
    connection_string: str = "",
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
) -> redis.Redis:
    normalized_connection_string = connection_string.strip()

    if normalized_connection_string:
        if normalized_connection_string.startswith(("redis://", "rediss://")):
            return redis.Redis.from_url(
                normalized_connection_string,
                decode_responses=True,
            )

        # Supports StackExchange.Redis style:
        # host:port,user=default,password=...,ssl=True,abortConnect=False
        parts = [part.strip() for part in normalized_connection_string.split(",") if part.strip()]
        host_part = parts[0]
        if ":" in host_part:
            redis_host, redis_port = host_part.rsplit(":", 1)
        else:
            redis_host, redis_port = host_part, str(port)

        options: Dict[str, str] = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            options[key.strip().lower()] = value.strip()

        use_ssl = options.get("ssl", "false").lower() == "true"
        redis_db = int(options.get("db", str(db)))
        username = options.get("user") or options.get("username")
        password = options.get("password")

        return redis.Redis(
            host=unquote(redis_host),
            port=int(redis_port),
            db=redis_db,
            username=unquote(username) if username else None,
            password=unquote(password) if password else None,
            ssl=use_ssl,
            decode_responses=True,
        )

    return redis.Redis(host=host, port=port, db=db, decode_responses=True)


class GraphRagQueueService:
    """Redis queue service using shared queues for both pipelines."""

    def __init__(self):
        redis_connection_string = os.getenv("REDIS_CONNECTION_STRING", "")
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))

        self.redis_client = _create_redis_client(
            connection_string=redis_connection_string,
            host=redis_host,
            port=redis_port,
            db=redis_db,
        )

        self.main_queue = os.getenv("REDIS_TASK_QUEUE", "document:task:queue:graph")
        self.processing_queue = os.getenv("REDIS_PROCESSING_QUEUE", "document:processing:queue:graph")
        self.failed_queue = os.getenv("REDIS_FAILED_QUEUE", "document:failed:queue:graph")
        self.dead_letter_queue = os.getenv("REDIS_DEAD_LETTER_QUEUE", "document:dead-letter:queue")

        self.result_prefix = os.getenv("WORKER_RESULT_PREFIX", "graphrag:result:")
        self.status_prefix = os.getenv("WORKER_STATUS_PREFIX", "graphrag:task:status:")
        self._sentinel_cache: Dict[str, str] = {}
        self._ensure_managed_queues_exist()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _status_key(self, task_id: str) -> str:
        return f"{self.status_prefix}{task_id}"

    @staticmethod
    def _normalize_pipeline_type(value: Any) -> Optional[str]:
        normalized = str(value or "").strip().lower()
        if normalized in {"graph", "graph-rag", "graph_rag", "graphrag", "graphworker", "graph-worker"}:
            return "graph"
        if normalized in {"rag", "rag-api", "rag_api", "ragworker", "rag-worker"}:
            return "rag"
        return None

    def _sentinel_payload(self, queue_name: str) -> str:
        cached = self._sentinel_cache.get(queue_name)
        if cached:
            return cached

        payload = json.dumps(
            {
                "sentinel": True,
                "type": "sentinel",
                "queue": queue_name,
            },
            separators=(",", ":"),
        )
        self._sentinel_cache[queue_name] = payload
        return payload

    def _is_sentinel_payload(self, raw_payload: Any, queue_name: Optional[str] = None) -> bool:
        if not isinstance(raw_payload, str):
            return False

        try:
            payload = json.loads(raw_payload)
        except Exception:
            return False

        if payload.get("sentinel") is not True and payload.get("type") != "sentinel":
            return False

        if queue_name is None:
            return True

        # Backward compatibility: the Wiki Backend previously created queue
        # sentinels without embedding the queue name. Treat those payloads as
        # valid sentinels so an idle/restarted worker never processes them as
        # real jobs.
        if "queue" not in payload:
            return True

        return payload.get("queue") == queue_name

    def _ensure_queue_exists(self, queue_name: str) -> None:
        if self.redis_client.exists(queue_name):
            return
        self.redis_client.rpush(queue_name, self._sentinel_payload(queue_name))

    def _ensure_managed_queues_exist(self) -> None:
        for queue_name in (
            self.main_queue,
            self.processing_queue,
            self.failed_queue,
            self.dead_letter_queue,
        ):
            self._ensure_queue_exists(queue_name)

    def _remove_queue_sentinel(self, queue_name: str) -> None:
        self.redis_client.lrem(queue_name, 0, self._sentinel_payload(queue_name))

    def _restore_queue_sentinel_if_empty(self, queue_name: str) -> None:
        if self.redis_client.llen(queue_name) == 0:
            self.redis_client.rpush(queue_name, self._sentinel_payload(queue_name))

    def _push_queue_item(self, queue_name: str, payload: Dict[str, Any]) -> None:
        self._remove_queue_sentinel(queue_name)
        self.redis_client.rpush(queue_name, json.dumps(payload))

    def enqueue_task(self, task_data: Dict[str, Any]) -> None:
        payload = dict(task_data)
        payload["type"] = "graph"
        payload["pipeline"] = "graph"
        self._push_queue_item(self.main_queue, payload)

    def get_queue_snapshot(self) -> Dict[str, Dict[str, Any]]:
        snapshot: Dict[str, Dict[str, Any]] = {}
        for queue_name in (
            self.main_queue,
            self.processing_queue,
            self.failed_queue,
            self.dead_letter_queue,
        ):
            items = self.redis_client.lrange(queue_name, 0, -1)
            visible_items = [
                item
                for item in items
                if not self._is_sentinel_payload(item, queue_name)
            ]
            snapshot[queue_name] = {
                "exists": bool(self.redis_client.exists(queue_name)),
                "length": len(items),
                "visible_items": len(visible_items),
                "sample": visible_items[:3],
            }
        return snapshot

    def claim_task_blocking(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        try:
            raw_payload = self.redis_client.execute_command(
                "BLMOVE",
                self.main_queue,
                self.processing_queue,
                "LEFT",
                "RIGHT",
                timeout,
            )
        except Exception:
            raw_payload = self.redis_client.brpoplpush(
                self.main_queue,
                self.processing_queue,
                timeout=timeout,
            )
        if not raw_payload:
            return None

        self._restore_queue_sentinel_if_empty(self.main_queue)

        # Detect sentinel value used to keep the queue key visible in Redis when
        # the queue is otherwise empty. Put it on the RIGHT so LEFT-pop workers
        # do not claim the sentinel ahead of real tasks.
        try:
            maybe_sentinel = json.loads(raw_payload)
            if maybe_sentinel.get("sentinel") is True or maybe_sentinel.get("type") == "sentinel":
                self.redis_client.lrem(self.processing_queue, 1, raw_payload)
                self.redis_client.rpush(self.main_queue, raw_payload)
                self._restore_queue_sentinel_if_empty(self.processing_queue)
                return None
        except Exception:
            pass

        task_data = json.loads(raw_payload)
        return {
            "raw_payload": raw_payload,
            "task": task_data,
        }

    def ack_processing_task(self, raw_payload: str) -> int:
        removed = int(self.redis_client.lrem(self.processing_queue, 1, raw_payload))
        self._restore_queue_sentinel_if_empty(self.processing_queue)
        return removed

    def release_unhandled_task(self, raw_payload: str) -> int:
        """Return a claimed task to main queue when it belongs to another worker type."""
        if not raw_payload:
            return 0

        removed = int(self.redis_client.lrem(self.processing_queue, 1, raw_payload))
        if not removed:
            return 0

        self._restore_queue_sentinel_if_empty(self.processing_queue)
        # Push released tasks to the opposite end so this worker does not
        # immediately reclaim the same non-owner payload on the next LEFT-pop.
        self._remove_queue_sentinel(self.main_queue)
        self.redis_client.rpush(self.main_queue, raw_payload)
        return removed

    def requeue_task(self, task_data: Dict[str, Any]) -> None:
        self._push_queue_item(self.main_queue, task_data)

    def push_failed_task(self, task_data: Dict[str, Any], reason: str) -> None:
        payload = dict(task_data)
        payload["failed_at"] = self._now_iso()
        payload["failed_reason"] = reason
        self._push_queue_item(self.failed_queue, payload)

    def push_dead_letter_task(self, task_data: Dict[str, Any], reason: str) -> None:
        payload = dict(task_data)
        payload["dead_lettered_at"] = self._now_iso()
        payload["dead_letter_reason"] = reason
        self._push_queue_item(self.dead_letter_queue, payload)

    def set_task_status(
        self,
        task_id: str,
        status: str,
        message: str = "",
        ttl_seconds: int = 86400,
        **extra_fields: Any,
    ) -> None:
        key = self._status_key(task_id)
        existing_raw = self.redis_client.get(key)
        existing = json.loads(existing_raw) if existing_raw else {}

        payload = {
            **existing,
            "task_id": task_id,
            "status": status,
            "message": message,
            "updated_at": self._now_iso(),
        }
        if extra_fields:
            payload.update(extra_fields)

        self.redis_client.setex(key, ttl_seconds, json.dumps(payload))
        print(
            f"[WORKER_STATUS] task_id={task_id} status={status} key={key} message={message}",
            flush=True,
        )
        logger.info(
            "Status updated | task_id=%s status=%s key=%s message=%s",
            task_id,
            status,
            key,
            message,
        )

    def set_result(self, task_id: str, result_data: Dict[str, Any], ttl_seconds: int = 86400) -> None:
        key = f"{self.result_prefix}{task_id}"
        self.redis_client.setex(key, ttl_seconds, json.dumps(result_data))
        print(f"[WORKER_RESULT] task_id={task_id} key={key}", flush=True)
        logger.info("Result stored | task_id=%s key=%s", task_id, key)


def extract_text_from_file(file_content: str, file_type: str) -> str:
    """Extract clean text from HTML or markdown/text content."""
    if file_type.lower() == "html":
        text = re.sub(r"<script[^>]*>.*?</script>", "", file_content, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    return file_content.strip()


def chunk_text(text: str, max_chunk_size: int = 500000, overlap: int = 200) -> list[str]:
    """Split text into chunks while keeping a small overlap for context continuity."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            sentences = re.split(r"(?<=[.!?])\s+", para)
            sentence_chunk = ""
            for sentence in sentences:
                if len(sentence_chunk) + len(sentence) + 1 > max_chunk_size:
                    if sentence_chunk:
                        chunks.append(sentence_chunk)
                    sentence_chunk = sentence[-overlap:] if overlap > 0 and len(sentence) > overlap else sentence
                else:
                    sentence_chunk = f"{sentence_chunk} {sentence}".strip()

            if sentence_chunk:
                current_chunk = sentence_chunk

        elif len(current_chunk) + len(para) + 2 > max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = para[-overlap:] if overlap > 0 and len(para) > overlap else para
        else:
            current_chunk = f"{current_chunk}\n\n{para}".strip() if current_chunk else para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class GraphRagWorker:
    """Redis-driven worker for Graph-RAG ingestion."""

    def __init__(self):
        self.queue_service = GraphRagQueueService()
        self.max_retries = int(os.getenv("WORKER_MAX_RETRIES", "3"))
        self.max_chunk_size = int(os.getenv("GRAPH_RAG_MAX_CHUNK_SIZE", "500000"))
        self.default_preset = os.getenv("GRAPH_RAG_DEFAULT_PRESET", "vietnam_history")
        self.stuck_timeout_seconds = int(os.getenv("GRAPH_RAG_STUCK_TIMEOUT_SECONDS", "900"))
        self.stuck_check_interval_seconds = int(os.getenv("GRAPH_RAG_STUCK_CHECK_INTERVAL_SECONDS", "30"))
        self.pipeline_webhook_url = os.getenv("PIPELINE_WEBHOOK_URL", "").strip()
        self.pipeline_webhook_token = os.getenv("PIPELINE_WEBHOOK_TOKEN", "").strip()
        self.pipeline_webhook_timeout = int(os.getenv("PIPELINE_WEBHOOK_TIMEOUT_SECONDS", "10"))
        self._last_stuck_check = 0.0

        self._shutdown_requested = False
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)

    def _handle_shutdown_signal(self, signum: int, _frame: Any) -> None:
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.warning("Received %s. Worker will stop after current task.", signal_name)
        self._shutdown_requested = True

    def _notify_pipeline_webhook(
        self,
        *,
        task_id: str,
        document_id: Optional[str],
        file_name: Optional[str],
        status: str,
        message: str,
        error: Optional[str] = None,
    ) -> None:
        if not self.pipeline_webhook_url:
            logger.warning(
                "[GRAPH_WEBHOOK_SKIPPED] task_id=%s reason=PIPELINE_WEBHOOK_URL not configured",
                task_id,
            )
            print(
                f"[GRAPH_WEBHOOK_SKIPPED] task_id={task_id} reason=PIPELINE_WEBHOOK_URL not configured",
                flush=True,
            )
            return

        if not task_id:
            logger.warning("[GRAPH_WEBHOOK_SKIPPED] reason=missing task_id")
            print("[GRAPH_WEBHOOK_SKIPPED] reason=missing task_id", flush=True)
            return

        payload = {
            "documentId": document_id,
            "taskId": task_id,
            "pipeline": "graph",
            "status": status,
            "message": message,
            "error": error,
            "fileName": file_name,
        }
        headers = {"Content-Type": "application/json"}
        if self.pipeline_webhook_token:
            headers["X-Webhook-Token"] = self.pipeline_webhook_token

        try:
            logger.info(
                "[GRAPH_WEBHOOK_CALLING] task_id=%s url=%s status=%s",
                task_id,
                self.pipeline_webhook_url,
                status,
            )
            print(
                f"[GRAPH_WEBHOOK_CALLING] task_id={task_id} url={self.pipeline_webhook_url} status={status}",
                flush=True,
            )
            response = requests.post(
                self.pipeline_webhook_url,
                json=payload,
                headers=headers,
                timeout=self.pipeline_webhook_timeout,
            )
            if response.status_code >= 400:
                logger.warning(
                    "[GRAPH_WEBHOOK_FAILED] task_id=%s http_status=%s body=%s",
                    task_id,
                    response.status_code,
                    response.text[:300],
                )
                print(
                    f"[GRAPH_WEBHOOK_FAILED] task_id={task_id} http_status={response.status_code}",
                    flush=True,
                )
            else:
                logger.info("[GRAPH_WEBHOOK_SUCCESS] task_id=%s http_status=%s", task_id, response.status_code)
                print(
                    f"[GRAPH_WEBHOOK_SUCCESS] task_id={task_id} http_status={response.status_code}",
                    flush=True,
                )
        except Exception as exc:
            logger.warning(
                "[GRAPH_WEBHOOK_FAILED] task_id=%s error=%s",
                task_id,
                str(exc),
            )
            print(
                f"[GRAPH_WEBHOOK_FAILED] task_id={task_id} error={str(exc)}",
                flush=True,
            )

    @staticmethod
    def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            # Support timestamps with trailing Z
            normalized = text.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except Exception:
            return None

    def _recover_stuck_processing_tasks(self) -> None:
        if self.stuck_timeout_seconds <= 0:
            return

        try:
            processing_items = self.queue_service.redis_client.lrange(
                self.queue_service.processing_queue,
                0,
                -1,
            )
        except Exception:
            logger.exception("Unable to scan processing queue for stuck tasks")
            return

        if not processing_items:
            return

        now = datetime.now(timezone.utc)
        recovered_count = 0

        for raw_payload in processing_items:
            if self.queue_service._is_sentinel_payload(raw_payload, self.queue_service.processing_queue):
                continue

            try:
                task_data = self._normalize_payload(json.loads(raw_payload))
            except Exception:
                continue

            task_owner = self.queue_service._normalize_pipeline_type(
                task_data.get("type") or task_data.get("pipeline")
            )
            if task_owner and task_owner != "graph":
                continue

            task_id = str(task_data.get("task_id") or "")
            if not task_id:
                continue

            status_key = self.queue_service._status_key(task_id)
            status_raw = self.queue_service.redis_client.get(status_key)
            status_payload = json.loads(status_raw) if status_raw else {}

            started_at = (
                self._parse_iso_timestamp(status_payload.get("processing_started_at"))
                or self._parse_iso_timestamp(status_payload.get("updated_at"))
                or self._parse_iso_timestamp(task_data.get("created_at"))
            )
            if not started_at:
                continue

            age_seconds = int((now - started_at).total_seconds())
            if age_seconds < self.stuck_timeout_seconds:
                continue

            retry_count = int(task_data.get("retry_count", 0))
            task_data["retry_count"] = retry_count + 1

            self.queue_service.ack_processing_task(raw_payload)

            if retry_count < self.max_retries:
                self.queue_service.requeue_task(task_data)
                self.queue_service.set_task_status(
                    task_id=task_id,
                    status=TASK_STATUS_PENDING,
                    message=(
                        "Watchdog moved stale processing task back to queue "
                        f"(retry {task_data['retry_count']}/{self.max_retries})"
                    ),
                    retry_count=task_data["retry_count"],
                    watchdog_recovered=True,
                    stale_age_seconds=age_seconds,
                )
            else:
                self.queue_service.push_failed_task(
                    task_data,
                    reason=(
                        "Watchdog marked stale processing task as failed "
                        f"after {age_seconds}s"
                    ),
                )
                self.queue_service.set_task_status(
                    task_id=task_id,
                    status=TASK_STATUS_FAILED,
                    message=(
                        "Watchdog marked stale processing task as failed "
                        f"after {age_seconds}s"
                    ),
                    retry_count=task_data["retry_count"],
                    watchdog_failed=True,
                    stale_age_seconds=age_seconds,
                )

            recovered_count += 1

        if recovered_count > 0:
            logger.warning(
                "Watchdog recovered %s stale processing task(s) from %s",
                recovered_count,
                self.queue_service.processing_queue,
            )

    def _normalize_payload(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(task_data or {})

        def pick(*keys: str) -> Any:
            for key in keys:
                value = normalized.get(key)
                if value is not None and value != "":
                    return value
            return None

        if not normalized.get("task_id"):
            normalized["task_id"] = pick("task_id", "taskId", "TaskId", "job_id", "jobId", "JobId", "id", "Id")

        pipeline_type = self.queue_service._normalize_pipeline_type(
            pick("type", "pipeline")
        )
        normalized["type"] = pipeline_type or "graph"
        normalized["pipeline"] = normalized["type"]

        if not normalized.get("job_id"):
            normalized["job_id"] = pick("job_id", "jobId", "JobId", "task_id", "taskId", "TaskId")

        if not normalized.get("document_id"):
            normalized["document_id"] = pick("document_id", "documentId", "DocumentId")

        if not normalized.get("file_path"):
            normalized["file_path"] = pick("file_path", "filePath", "FilePath", "file_url", "fileUrl", "FileUrl", "url", "Url")

        if not normalized.get("file_url") and normalized.get("file_path"):
            normalized["file_url"] = normalized.get("file_path")

        if not normalized.get("file_name"):
            normalized["file_name"] = pick("file_name", "fileName", "FileName")

        if not normalized.get("target_person"):
            normalized["target_person"] = pick("target_person", "targetPerson", "TargetPerson", "person_name", "personName")

        if not normalized.get("preset"):
            normalized["preset"] = pick("preset", "Preset")

        if not normalized.get("use_original_prompt"):
            normalized["use_original_prompt"] = pick("use_original_prompt", "useOriginalPrompt")

        if not normalized.get("retry_count"):
            normalized["retry_count"] = pick("retry_count", "retryCount")

        file_type = str(
            pick("file_type", "fileType", "FileType") or ""
        ).strip().lower()
        if not file_type:
            file_type = "unknown"
        normalized["file_type"] = file_type

        if not normalized.get("file_name"):
            parsed = urlparse(str(normalized.get("file_path") or ""))
            derived_name = Path(parsed.path).name or "document"
            ext = f".{file_type}" if file_type and file_type != "unknown" else ""
            normalized["file_name"] = derived_name if "." in derived_name else f"{derived_name}{ext}"

        if not normalized.get("target_person"):
            normalized["target_person"] = Path(normalized["file_name"]).stem

        if not normalized.get("preset"):
            normalized["preset"] = self.default_preset

        normalized["use_original_prompt"] = _parse_bool(
            normalized.get("use_original_prompt"),
            default=True,
        )

        try:
            normalized["retry_count"] = int(normalized.get("retry_count") or 0)
        except (TypeError, ValueError):
            normalized["retry_count"] = 0

        return normalized

    def _download_file_text(self, file_url: str) -> str:
        headers = {
            "User-Agent": "GraphRAG-Wiki/1.0 (https://github.com/graphrag; contact@graphrag.local) python-requests"
        }
        response = requests.get(file_url, headers=headers, timeout=120)
        response.raise_for_status()

        encoding = response.encoding or "utf-8"
        try:
            return response.content.decode(encoding)
        except UnicodeDecodeError:
            return response.content.decode("utf-8", errors="replace")

    def _ensure_person_node(self, db: GraphDB, person_name: str) -> None:
        with db.driver.session(database=db.database) as session:
            exists = session.run(
                "MATCH (p:Person {name: $name}) RETURN COUNT(p) as cnt",
                name=person_name,
            ).single()
            if exists and exists.get("cnt", 0) > 0:
                return

            session.run(
                "CREATE (p:Person {name: $name}) RETURN p",
                name=person_name,
            )

    def _process_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(task_data["task_id"])
        file_url = str(task_data.get("file_path") or "")
        file_name = str(task_data.get("file_name") or "document")
        target_person = str(task_data.get("target_person") or "unknown")
        preset = str(task_data.get("preset") or self.default_preset)
        use_original_prompt = bool(task_data.get("use_original_prompt", True))

        file_ext = Path(file_name).suffix.lower().lstrip(".")
        if not file_ext or file_ext == "unknown":
            file_ext = str(task_data.get("file_type") or "").lower().strip()
        if file_ext in {"markdown"}:
            file_ext = "md"

        if file_ext not in {"html", "md", "txt"}:
            raise ValueError(f"Unsupported file type for Graph-RAG worker: {file_ext}")

        raw_content = self._download_file_text(file_url)
        clean_text = extract_text_from_file(raw_content, "html" if file_ext == "html" else "md")
        if not clean_text.strip():
            raise ValueError("Downloaded file content is empty after extraction")

        db = GraphDB()
        extractor = CustomGraphExtractor(graph_db=db)

        try:
            self._ensure_person_node(db, target_person)

            if preset:
                extractor.set_preset(preset)

            chunks = chunk_text(clean_text, max_chunk_size=self.max_chunk_size)
            total_nodes = 0
            total_relationships = 0

            for index, chunk in enumerate(chunks, start=1):
                self.queue_service.set_task_status(
                    task_id=task_id,
                    status=TASK_STATUS_PROCESSING,
                    message=f"Processing chunk {index}/{len(chunks)}",
                    progress={
                        "current": index - 1,
                        "total": len(chunks),
                        "percent": int(((index - 1) / len(chunks)) * 100),
                    },
                    target_person=target_person,
                    preset=preset,
                    file_name=file_name,
                )

                nodes_created, rels_created = extractor.enrich_text(
                    chunk,
                    source_chunk_id=f"{file_name}_chunk_{index}",
                    link_to_person=target_person,
                    use_original_prompt=use_original_prompt,
                )
                total_nodes += nodes_created
                total_relationships += rels_created

            result = {
                "task_id": task_id,
                "status": "completed",
                "target_person": target_person,
                "file_name": file_name,
                "preset": preset,
                "use_original_prompt": use_original_prompt,
                "chunks_processed": len(chunks),
                "nodes_created": total_nodes,
                "relationships_created": total_relationships,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            return result
        finally:
            db.close()

    def run(self) -> None:
        logger.info("=" * 72)
        logger.info("GRAPH-RAG REDIS WORKER STARTED")
        logger.info("Queue(main): %s", self.queue_service.main_queue)
        logger.info("Queue(processing): %s", self.queue_service.processing_queue)
        logger.info("Queue(failed): %s", self.queue_service.failed_queue)
        logger.info("=" * 72)

        processed_count = 0
        idle_seconds = 0

        while not self._shutdown_requested:
            now_monotonic = time.monotonic()
            if now_monotonic - self._last_stuck_check >= self.stuck_check_interval_seconds:
                self._recover_stuck_processing_tasks()
                self._last_stuck_check = now_monotonic

            claimed = self.queue_service.claim_task_blocking(timeout=5)
            if not claimed:
                idle_seconds += 5
                if idle_seconds % 30 == 0:
                    logger.info("Worker idle for %ss (processed=%s)", idle_seconds, processed_count)
                continue

            idle_seconds = 0
            raw_payload = claimed["raw_payload"]

            # Defensive guard: sentinel payload should have been filtered in claim_task_blocking,
            # but never treat it as a real task if it leaks through.
            if self.queue_service._is_sentinel_payload(raw_payload, self.queue_service.main_queue):
                logger.debug("Skipping leaked sentinel payload in worker loop")
                if raw_payload:
                    self.queue_service.ack_processing_task(raw_payload)
                self.queue_service._restore_queue_sentinel_if_empty(self.queue_service.main_queue)
                continue

            task_data = self._normalize_payload(claimed["task"])
            should_ack = True
            task_owner = self.queue_service._normalize_pipeline_type(
                task_data.get("type") or task_data.get("pipeline")
            )
            if task_owner not in {"graph", None}:
                released = self.queue_service.release_unhandled_task(raw_payload)
                should_ack = False
                logger.info(
                    "Released non-graph task back to shared queue | owner=%s removed=%s",
                    task_owner,
                    released,
                )
                continue

            task_id = str(task_data.get("task_id") or "")
            logger.info(
                "GRAPH_WORKER_JOB_CLAIMED | task_id=%s | file_name=%s | target_person=%s | retry_count=%s",
                task_id or "<missing>",
                task_data.get("file_name"),
                task_data.get("target_person"),
                task_data.get("retry_count"),
            )
            print(
                "[GRAPH_WORKER_JOB_CLAIMED] "
                f"task_id={task_id or '<missing>'} "
                f"file_name={task_data.get('file_name')} "
                f"target_person={task_data.get('target_person')} "
                f"retry_count={task_data.get('retry_count')}",
                flush=True,
            )

            try:
                if not task_id:
                    raise ValueError("Task payload missing task_id/job_id")

                retry_count = int(task_data.get("retry_count", 0))
                if retry_count > self.max_retries:
                    self.queue_service.push_failed_task(
                        task_data,
                        reason=(
                            "Task retry_count exceeded configured limit "
                            f"({self.max_retries}) before execution"
                        ),
                    )
                    self.queue_service.push_dead_letter_task(
                        task_data,
                        reason=(
                            "Task retry_count exceeded configured limit "
                            f"({self.max_retries})"
                        ),
                    )
                    self.queue_service.set_task_status(
                        task_id=task_id,
                        status=TASK_STATUS_FAILED,
                        message="Task moved to dead-letter queue before execution",
                        retry_count=retry_count,
                        failed_queue=self.queue_service.failed_queue,
                        dead_letter_queue=self.queue_service.dead_letter_queue,
                        dead_lettered=True,
                    )
                    continue

                logger.info("Task picked up: %s", task_id)
                self.queue_service.set_task_status(
                    task_id=task_id,
                    status=TASK_STATUS_PROCESSING,
                    message="Worker picked up task",
                    retry_count=retry_count,
                    processing_started_at=datetime.now(timezone.utc).isoformat(),
                    file_name=task_data.get("file_name"),
                    target_person=task_data.get("target_person"),
                    progress={"current": 0, "total": 1, "percent": 0},
                )

                logger.info(
                    "GRAPH_WORKER_JOB_STARTED | task_id=%s | file_name=%s | target_person=%s",
                    task_id,
                    task_data.get("file_name"),
                    task_data.get("target_person"),
                )
                print(
                    "[GRAPH_WORKER_JOB_STARTED] "
                    f"task_id={task_id} "
                    f"file_name={task_data.get('file_name')} "
                    f"target_person={task_data.get('target_person')}",
                    flush=True,
                )

                result = self._process_task(task_data)
                self.queue_service.set_result(task_id, result)
                status_extra = {
                    key: value
                    for key, value in result.items()
                    if key not in {"task_id", "status", "message", "updated_at"}
                }
                self.queue_service.set_task_status(
                    task_id=task_id,
                    status=TASK_STATUS_COMPLETED,
                    message="Graph-RAG extraction completed",
                    progress={"current": 1, "total": 1, "percent": 100},
                    **status_extra,
                )
                self._notify_pipeline_webhook(
                    task_id=task_id,
                    document_id=str(task_data.get("document_id") or "") or None,
                    file_name=task_data.get("file_name"),
                    status="completed",
                    message="Graph-RAG extraction completed",
                )
                processed_count += 1
                logger.info(
                    "Task completed: %s (nodes=%s, rels=%s)",
                    task_id,
                    result.get("nodes_created"),
                    result.get("relationships_created"),
                )
            except Exception as exc:
                retry_count = int(task_data.get("retry_count", 0)) + 1
                task_data["retry_count"] = retry_count

                logger.error("Task failed: %s | %s", task_id or "unknown", str(exc), exc_info=True)

                if not task_id:
                    logger.warning(
                        "Skipping failed-queue push for invalid payload without task_id: %s",
                        str(exc),
                    )
                    continue

                self.queue_service.push_failed_task(task_data, reason=str(exc))

                if task_id and retry_count <= self.max_retries:
                    self.queue_service.requeue_task(task_data)
                    self.queue_service.set_task_status(
                        task_id=task_id,
                        status=TASK_STATUS_PENDING,
                        message=(
                            f"Task failed and was requeued for retry {retry_count}/{self.max_retries}"
                        ),
                        error=str(exc),
                        retry_count=retry_count,
                        file_name=task_data.get("file_name"),
                        target_person=task_data.get("target_person"),
                        failed_queue=self.queue_service.failed_queue,
                        next_queue=self.queue_service.main_queue,
                    )
                else:
                    self.queue_service.push_dead_letter_task(task_data, reason=str(exc))
                    if task_id:
                        self.queue_service.set_task_status(
                            task_id=task_id,
                            status=TASK_STATUS_FAILED,
                            message="Task failed permanently",
                            error=str(exc),
                            retry_count=retry_count,
                            file_name=task_data.get("file_name"),
                            target_person=task_data.get("target_person"),
                            failed_queue=self.queue_service.failed_queue,
                            dead_letter_queue=self.queue_service.dead_letter_queue,
                            dead_lettered=True,
                        )
                        self._notify_pipeline_webhook(
                            task_id=task_id,
                            document_id=str(task_data.get("document_id") or "") or None,
                            file_name=task_data.get("file_name"),
                            status="failed",
                            message="Task failed permanently",
                            error=str(exc),
                        )
            finally:
                if raw_payload and should_ack:
                    removed = self.queue_service.ack_processing_task(raw_payload)
                    logger.debug("Ack processing queue for task %s, removed=%s", task_id, removed)

        logger.info("Worker stopped.")


if __name__ == "__main__":
    start = time.time()
    try:
        worker = GraphRagWorker()
        worker.run()
    except Exception as exc:
        logger.error("Worker crashed at startup: %s", str(exc), exc_info=True)
        raise
    finally:
        logger.info("Worker runtime: %.2fs", time.time() - start)
