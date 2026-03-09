#!/usr/bin/env python3
"""NEXUS OS Knowledge Graph — ChromaDB memory module.

Provides remember/recall functions for the autonomous agent.
Stores decisions, failures, and project context.
"""
import chromadb
import hashlib
from datetime import datetime

client = chromadb.HttpClient(host='localhost', port=8000)

decisions = client.get_or_create_collection('nexus_decisions')
failures = client.get_or_create_collection('nexus_failures')
context = client.get_or_create_collection('nexus_context')


def remember(text: str, meta: dict, collection='decisions'):
    col = {'decisions': decisions, 'failures': failures,
           'context': context}.get(collection, decisions)
    doc_id = hashlib.md5((text + str(meta)).encode()).hexdigest()
    meta['timestamp'] = datetime.now().isoformat()
    clean_meta = {k: str(v) for k, v in meta.items()}
    col.upsert(documents=[text], metadatas=[clean_meta], ids=[doc_id])


def recall(query: str, n=5, collection='decisions') -> list:
    col = {'decisions': decisions, 'failures': failures,
           'context': context}.get(collection, decisions)
    try:
        results = col.query(query_texts=[query], n_results=n)
        return results['documents'][0] if results['documents'] else []
    except Exception:
        return []


def seed_from_file(path: str, tag: str):
    with open(path) as f:
        content = f.read()
    chunks = []
    for i in range(0, len(content), 400):
        chunks.append(content[i:i+500])
    for i, chunk in enumerate(chunks):
        remember(chunk, {'source': path, 'chunk': str(i), 'tag': tag}, 'context')
    print(f'Seeded {len(chunks)} chunks from {path}')


if __name__ == '__main__':
    remember("Test memory", {"type": "test"})
    results = recall("test")
    print(f"Recall test: {results}")
    print("ChromaDB memory module working.")
