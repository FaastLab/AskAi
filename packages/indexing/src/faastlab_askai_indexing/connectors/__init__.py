"""Connectors — pull source documents into the pipeline."""

from faastlab_askai_indexing.connectors.base import Connector, SourceDocument
from faastlab_askai_indexing.connectors.filesystem import FilesystemConnector
from faastlab_askai_indexing.connectors.s3 import S3Connector

__all__ = [
    "Connector",
    "FilesystemConnector",
    "S3Connector",
    "SourceDocument",
]
