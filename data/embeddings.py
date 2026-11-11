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


def embed_documents(conn: psycopg.Connection) -> int:
    """Rebuild the search index from the warehouse's documents. Returns how many were indexed."""
    # shortcut: re-embeds every document on every build and indexes each one whole; fine for
    # notes and emails, split long documents into passages and embed only changes when they grow.
    documents = conn.execute(
        "select doc_id, account_id, kind, title, author, created_at, body from staging.stg_documents"
    ).fetchall()
    with conn.transaction():
        conn.execute("delete from vec.document_chunks")
        with conn.cursor() as cursor:
            cursor.executemany(
                "insert into vec.document_chunks "
                "(doc_id, account_id, kind, title, author, created_at, body, embedding) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
                [(*doc, as_vector(embed(f"{doc[3]} {doc[6]}"))) for doc in documents],
            )
    return len(documents)
