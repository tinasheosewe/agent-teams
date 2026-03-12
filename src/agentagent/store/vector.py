"""ChromaDB vector store wrapper for historian semantic search."""

from __future__ import annotations

from typing import TYPE_CHECKING

import chromadb

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection


class VectorStore:
    """Wraps ChromaDB for semantic search over discussion content."""

    def __init__(self, persist_dir: str = "data/chroma") -> None:
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection: Collection = self._client.get_or_create_collection(
            name="knowledge",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, doc_id: str, text: str, metadata: dict[str, str]) -> None:
        """Add or update a document in the vector store."""
        self._collection.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])

    def query(self, text: str, n_results: int = 5, where: dict | None = None) -> list[dict]:
        """Semantic search. Returns list of {id, text, metadata, distance}."""
        kwargs: dict = {"query_texts": [text], "n_results": n_results}
        if where:
            kwargs["where"] = where
        results = self._collection.query(**kwargs)
        items: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                items.append(
                    {
                        "id": doc_id,
                        "text": results["documents"][0][i] if results["documents"] else "",
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                    }
                )
        return items

    def delete_project(self, project_id: str) -> None:
        """Remove all documents for a project."""
        self._collection.delete(where={"project_id": project_id})
