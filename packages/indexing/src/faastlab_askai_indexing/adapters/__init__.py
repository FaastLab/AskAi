"""Concrete adapter implementations.

These satisfy the Protocols defined in `faastlab_askai_core.adapters`.
The factory in `faastlab_askai_core.factory` chooses which to use at
startup based on `Settings`.
"""

from faastlab_askai_indexing.adapters.embeddings_openai import OpenAIEmbeddings
from faastlab_askai_indexing.adapters.storage_minio import MinIOStorage
from faastlab_askai_indexing.adapters.vector_pgvector import PgVectorStore

__all__ = ["MinIOStorage", "OpenAIEmbeddings", "PgVectorStore"]
