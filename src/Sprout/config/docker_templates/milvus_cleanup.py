"""Drop the six-lane Milvus collections so a run starts from a clean schema.

Milvus collections are schema-bound: the embedding width is fixed when the
collection is created. Live tests that construct stores with a smaller width
(for speed) therefore leave collections the fan-out cannot write into later —
the writes fail per lane and are logged, never raised, so the symptom is
"Milvus is empty" rather than an error.

Run it before a fresh round of live tests, or after switching embedding models:

    docker compose run --rm -T sprout-app python /app/docker/milvus_cleanup.py
    python docker/milvus_cleanup.py milvus://127.0.0.1:19530     # host, native

The collections are derived lanes, so dropping them is always safe: the next
write re-creates the schema and re-mirrors from the authority.
"""

from __future__ import annotations

import os
import sys

from pymilvus import MilvusClient

COLLECTIONS = (
    "sprout_sessions",  # reserved session scalar rows
    "sprout_vec_messages",  # message/turn vectors
    "sprout_vec_tasks",  # task vectors
    "sprout_vec_knowledge_chunks",  # knowledge/memory-fact vectors
    "sprout_vec_skills",  # skill vectors
    "sprout_vec_context_snapshots",  # context snapshot vectors
)


def main(argv: list[str]) -> int:
    raw = argv[1] if len(argv) > 1 else os.environ.get(
        "SPROUT_MILVUS_URI", "http://sprout-milvus:19530"
    )
    uri = raw.replace("milvus://", "http://", 1)
    print(f"milvus: {uri}")
    client = MilvusClient(uri=uri)
    for name in COLLECTIONS:
        if client.has_collection(name):
            client.drop_collection(name)
            print(f"dropped {name}")
        else:
            print(f"absent  {name}")
    client.close()
    print("cleanup done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
