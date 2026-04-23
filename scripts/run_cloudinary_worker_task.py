import json
import time
import uuid

from worker import GraphRagQueueService


CLOUDINARY_URL = (
    "https://res.cloudinary.com/do65kca8j/raw/upload/v1776874372/"
    "wiki-documents/534e2044-060d-4d7a-b07b-b4bef30c90a7-"
    "Tr%E1%BA%A7n%20H%C6%B0ng%20%C4%90%E1%BA%A1o.html"
)


def main() -> int:
    task_id = f"tran-hung-dao-{uuid.uuid4().hex[:10]}"
    queue_service = GraphRagQueueService()

    payload = {
        "type": "graph",
        "task_id": task_id,
        "file_path": CLOUDINARY_URL,
        "file_name": "Tran_Hung_Dao.html",
        "file_type": "html",
        "target_person": "Trần Hưng Đạo",
        "preset": "minimal",
        "use_original_prompt": False,
        "retry_count": 0,
    }

    queue_service.enqueue_task(payload)
    print(f"ENQUEUED {task_id}")
    print(f"QUEUE {queue_service.main_queue}")

    status_key = f"{queue_service.status_prefix}{task_id}"
    result_key = f"{queue_service.result_prefix}{task_id}"

    start_time = time.time()
    last_status = None

    while time.time() - start_time < 300:
        raw_status = queue_service.redis_client.get(status_key)
        if raw_status:
            status = json.loads(raw_status)
            current = status.get("status")
            if current != last_status:
                print(f"STATUS {current} MESSAGE {status.get('message')}")
                last_status = current
            if current in {"COMPLETED", "FAILED"}:
                break
        time.sleep(2)

    final_status_raw = queue_service.redis_client.get(status_key)
    final_result_raw = queue_service.redis_client.get(result_key)

    print(f"FINAL_STATUS_JSON {final_status_raw if final_status_raw else '<none>'}")
    print(f"FINAL_RESULT_JSON {final_result_raw if final_result_raw else '<none>'}")

    if not final_status_raw:
        return 2

    final_status = json.loads(final_status_raw).get("status")
    if final_status == "COMPLETED":
        return 0
    if final_status == "FAILED":
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
