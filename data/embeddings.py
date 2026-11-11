"""Document embeddings for search, with no model download and no paid key.

Words are hashed into a fixed number of dimensions (the "hashing trick"), so a query matches a
document that shares its words. That is enough for the demo's notes and emails, and it is
deterministic, which the tests and evals rely on.
"""

import hashlib
import math
import re

import psycopg

DIMENSIONS = 256
WORD = re.compile(r"[a-z0-9]+")
# Words too common to tell documents apart.
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "so",
        "the",
        "to",
        "was",
        "we",
        "were",
        "with",
    ]
)


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in WORD.findall(text.lower()):
        if word in STOP_WORDS:
            continue
        digest = hashlib.sha256(word.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        vector[index] += 1.0 if digest[4] % 2 else -1.0
    length = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / length for v in vector]


def as_vector(values: list[float]) -> str:
    """The text form pgvector accepts, so no extra database adapter is needed."""
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


COLUMNS = "doc_id, account_id, kind, title, author, created_at, body"


def embed_documents(conn: psycopg.Connection) -> int:
    """Bring the search index up to date with the warehouse's documents. Returns how many it embedded.

    Only new and changed documents are embedded; documents gone from the warehouse are removed.
    """
    # shortcut: each document is indexed whole, fine for notes and emails; split long documents
    # into passages when they grow past a few pages.
    changed = conn.execute(
        f"select {COLUMNS} from staging.stg_documents d "
        f"except select {COLUMNS} from vec.document_chunks"
    ).fetchall()
    with conn.transaction():
        conn.execute(
            "delete from vec.document_chunks "
            "where doc_id not in (select doc_id from staging.stg_documents)"
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                f"insert into vec.document_chunks ({COLUMNS}, embedding) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s::vector) "
                "on conflict (doc_id) do update set account_id = excluded.account_id, "
                "kind = excluded.kind, title = excluded.title, author = excluded.author, "
                "created_at = excluded.created_at, body = excluded.body, "
                "embedding = excluded.embedding",
                [(*doc, as_vector(embed(f"{doc[3]} {doc[6]}"))) for doc in changed],
            )
    return len(changed)
