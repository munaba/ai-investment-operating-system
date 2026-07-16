from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from Core.exceptions import DatabaseError
from Core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VectorRecord:
    """A single record to be stored in a vector store.

    Attributes:
        id: Unique identifier for the record.
        document: The raw text content that will be (or was) embedded.
        metadata: Optional free-form metadata associated with the record
            (e.g. source, ticker symbol, timestamp) usable for filtering.
        embedding: Optional precomputed embedding vector. If omitted, the
            underlying vector store implementation is expected to compute
            it automatically.
    """

    id: str
    document: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


@dataclass
class VectorSearchResult:
    """A single result returned from a similarity search.

    Attributes:
        id: Identifier of the matched record.
        document: The text content of the matched record.
        metadata: Metadata associated with the matched record.
        distance: Similarity/distance score (lower usually means more similar,
            but the exact semantics depend on the backend implementation).
    """

    id: str
    document: str
    metadata: Dict[str, Any]
    distance: Optional[float] = None


class VectorStore(ABC):
    """Abstract interface for a vector similarity search backend.

    All callers in this project must depend only on this interface — never
    on a concrete backend (e.g. ChromaDB) directly — so the underlying
    vector database can be swapped without changing calling code.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish any resources/connections needed to use this store.

        Raises:
            DatabaseError: If the connection cannot be established.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Release any resources/connections held by this store."""
        raise NotImplementedError

    @abstractmethod
    def add(self, collection_name: str, records: List[VectorRecord]) -> None:
        """Add new records to a collection.

        Args:
            collection_name: Name of the target collection.
            records: Records to insert.

        Raises:
            DatabaseError: If the records could not be added.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, collection_name: str, records: List[VectorRecord]) -> None:
        """Update existing records in a collection.

        Args:
            collection_name: Name of the target collection.
            records: Records to update, matched by their ``id``.

        Raises:
            DatabaseError: If the records could not be updated.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, collection_name: str, ids: List[str]) -> None:
        """Delete records from a collection by id.

        Args:
            collection_name: Name of the target collection.
            ids: Identifiers of the records to delete.

        Raises:
            DatabaseError: If the records could not be deleted.
        """
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[VectorSearchResult]:
        """Search a collection for records most similar to ``query``.

        Args:
            collection_name: Name of the collection to search.
            query: Natural-language query text.
            top_k: Maximum number of results to return.
            where: Optional metadata filter (backend-specific semantics).

        Returns:
            A list of matching records ordered from most to least similar.

        Raises:
            DatabaseError: If the search fails.
        """
        raise NotImplementedError

    @abstractmethod
    def count(self, collection_name: str) -> int:
        """Count the number of records stored in a collection.

        Args:
            collection_name: Name of the target collection.

        Returns:
            The number of records in the collection.

        Raises:
            DatabaseError: If the count could not be retrieved.
        """
        raise NotImplementedError

    @abstractmethod
    def clear(self, collection_name: str) -> None:
        """Remove all records from a collection.

        Args:
            collection_name: Name of the target collection.

        Raises:
            DatabaseError: If the collection could not be cleared.
        """
        raise NotImplementedError


class ChromaVectorStore(VectorStore):
    """ChromaDB-backed implementation of the :class:`VectorStore` interface.

    ``chromadb`` is imported lazily inside :meth:`connect` so that simply
    importing this module (or the rest of the ``Database`` package) never
    requires ChromaDB to be installed — only code paths that actually use
    :class:`ChromaVectorStore` do.

    Attributes:
        persist_directory: Filesystem directory where ChromaDB persists data.
    """

    def __init__(self, persist_directory: str = "chroma_data") -> None:
        """Initialize the store without opening any connection yet.

        Args:
            persist_directory: Directory ChromaDB should persist data to.
        """
        self.persist_directory: str = persist_directory
        self._client: Any = None
        self._collections: Dict[str, Any] = {}

    def connect(self) -> None:
        """Create the underlying ChromaDB persistent client.

        Raises:
            DatabaseError: If ``chromadb`` is not installed, or the client
                fails to initialize.
        """
        if self._client is not None:
            return
        try:
            import chromadb  
        except ImportError as exc:
            raise DatabaseError(
                "chromadb is not installed. Install it with 'pip install chromadb' "
                "to use ChromaVectorStore."
            ) from exc

        try:
            self._client = chromadb.PersistentClient(path=self.persist_directory)
            logger.debug(f"Connected to ChromaDB at '{self.persist_directory}'")
        except Exception as exc:  # noqa: BLE001 - chromadb raises backend-specific errors
            raise DatabaseError("Failed to initialize ChromaDB client", details={"error": str(exc)}) from exc

    def disconnect(self) -> None:
        """Release the ChromaDB client reference."""
        self._client = None
        self._collections.clear()
        logger.debug("Disconnected from ChromaDB")

    def _get_collection(self, collection_name: str) -> Any:
        """Get (creating if needed) a cached ChromaDB collection handle.

        Args:
            collection_name: Name of the collection.

        Returns:
            The underlying ChromaDB collection object.

        Raises:
            DatabaseError: If not connected, or the collection cannot be fetched.
        """
        if self._client is None:
            raise DatabaseError("ChromaVectorStore is not connected. Call connect() first.")

        if collection_name in self._collections:
            return self._collections[collection_name]

        try:
            collection = self._client.get_or_create_collection(name=collection_name)
            self._collections[collection_name] = collection
            return collection
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to get or create collection '{collection_name}'", details={"error": str(exc)}
            ) from exc

    def add(self, collection_name: str, records: List[VectorRecord]) -> None:
        """Add records to a ChromaDB collection. See :meth:`VectorStore.add`."""
        if not records:
            return
        collection = self._get_collection(collection_name)
        try:
            collection.add(
                ids=[record.id for record in records],
                documents=[record.document for record in records],
                metadatas=[record.metadata for record in records],
                embeddings=[record.embedding for record in records] if records[0].embedding else None,
            )
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to add records to collection '{collection_name}'", details={"error": str(exc)}
            ) from exc

    def update(self, collection_name: str, records: List[VectorRecord]) -> None:
        """Update records in a ChromaDB collection. See :meth:`VectorStore.update`."""
        if not records:
            return
        collection = self._get_collection(collection_name)
        try:
            collection.update(
                ids=[record.id for record in records],
                documents=[record.document for record in records],
                metadatas=[record.metadata for record in records],
                embeddings=[record.embedding for record in records] if records[0].embedding else None,
            )
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to update records in collection '{collection_name}'", details={"error": str(exc)}
            ) from exc

    def delete(self, collection_name: str, ids: List[str]) -> None:
        """Delete records from a ChromaDB collection. See :meth:`VectorStore.delete`."""
        if not ids:
            return
        collection = self._get_collection(collection_name)
        try:
            collection.delete(ids=ids)
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to delete records from collection '{collection_name}'", details={"error": str(exc)}
            ) from exc

    def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[VectorSearchResult]:
        """Search a ChromaDB collection. See :meth:`VectorStore.search`."""
        collection = self._get_collection(collection_name)
        try:
            raw = collection.query(query_texts=[query], n_results=top_k, where=where)
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to search collection '{collection_name}'", details={"error": str(exc)}
            ) from exc

        results: List[VectorSearchResult] = []
        ids = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0] if raw.get("distances") else [None] * len(ids)

        for record_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            results.append(
                VectorSearchResult(id=record_id, document=document, metadata=metadata or {}, distance=distance)
            )
        return results

    def count(self, collection_name: str) -> int:
        """Count records in a ChromaDB collection. See :meth:`VectorStore.count`."""
        collection = self._get_collection(collection_name)
        try:
            return collection.count()
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to count collection '{collection_name}'", details={"error": str(exc)}
            ) from exc

    def clear(self, collection_name: str) -> None:
        """Remove all records from a ChromaDB collection. See :meth:`VectorStore.clear`."""
        if self._client is None:
            raise DatabaseError("ChromaVectorStore is not connected. Call connect() first.")
        try:
            self._client.delete_collection(name=collection_name)
            self._collections.pop(collection_name, None)
        except Exception as exc:  
            raise DatabaseError(
                f"Failed to clear collection '{collection_name}'", details={"error": str(exc)}
            ) from exc