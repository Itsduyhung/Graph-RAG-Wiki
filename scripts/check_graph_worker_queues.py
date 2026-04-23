import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import GraphRagQueueService


def main() -> int:
    queue_service = GraphRagQueueService()
    snapshot = queue_service.get_queue_snapshot()

    print("GRAPH_RAG_QUEUE_SNAPSHOT")
    for queue_name, info in snapshot.items():
        print(
            json.dumps(
                {
                    "queue": queue_name,
                    "exists": info["exists"],
                    "length": info["length"],
                    "visible_items": info["visible_items"],
                },
                ensure_ascii=False,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())