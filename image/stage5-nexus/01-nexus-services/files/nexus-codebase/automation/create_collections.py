#!/usr/bin/env python3
"""
Create ChromaDB collections for the NEXUS CAF knowledge base.
Connects to the local ChromaDB instance at http://localhost:8000.
Uses get_or_create_collection so existing collections are untouched.
"""

import sys
import chromadb

CHROMA_HOST = "localhost"
CHROMA_PORT = 8000

# New collections to create for the CAF indexing pipeline
NEW_COLLECTIONS = [
    ("code_chunks",        "Python, Solidity, Bash, YAML source code chunks"),
    ("docs_chunks",        "Markdown documentation sections"),
    ("infra_configs",      "Systemd services, iptables, Geth/IPFS config files"),
    ("session_transcripts","Conversation turn pairs from agent sessions"),
    ("web_research",       "Web search results for Phase 7 research tasks"),
]


def main():
    print(f"Connecting to ChromaDB at http://{CHROMA_HOST}:{CHROMA_PORT} ...")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    # Verify connection
    try:
        client.heartbeat()
        print("  OK — ChromaDB is reachable\n")
    except Exception as e:
        print(f"  ERROR: cannot reach ChromaDB — {e}", file=sys.stderr)
        sys.exit(1)

    # Create (or retrieve) the new collections
    print("Creating new collections (get_or_create — existing ones are untouched):")
    for name, description in NEW_COLLECTIONS:
        col = client.get_or_create_collection(
            name=name,
            metadata={"description": description, "project": "nexus-caf"},
        )
        print(f"  + {name:<22} (id={col.id})")

    # List ALL collections with doc counts
    print("\nAll collections in ChromaDB:")
    print(f"  {'Collection':<25} {'Docs':>6}")
    print(f"  {'-'*25} {'-'*6}")

    all_collections = client.list_collections()
    total_docs = 0
    for col in sorted(all_collections, key=lambda c: c.name):
        count = col.count()
        total_docs += count
        print(f"  {col.name:<25} {count:>6}")

    print(f"\n  Total collections: {len(all_collections)}")
    print(f"  Total documents  : {total_docs}")

    # Sanity check — all 8 expected collections present
    expected = {
        "nexus_decisions", "nexus_failures", "nexus_context",
        "code_chunks", "docs_chunks", "infra_configs",
        "session_transcripts", "web_research",
    }
    found = {c.name for c in all_collections}
    missing = expected - found
    if missing:
        print(f"\n  WARNING: missing expected collections: {missing}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\n  All {len(expected)} expected collections present.")


if __name__ == "__main__":
    main()
