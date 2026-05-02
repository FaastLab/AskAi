"""Content-hash tests."""

from __future__ import annotations

from faastlab_askai_indexing.hashing import content_hash


def test_content_hash_is_stable() -> None:
    assert content_hash(b"hello world") == content_hash(b"hello world")


def test_content_hash_changes_with_data() -> None:
    assert content_hash(b"a") != content_hash(b"b")


def test_content_hash_is_hex_sha256() -> None:
    digest = content_hash(b"x")
    assert len(digest) == 64  # SHA-256 = 32 bytes = 64 hex chars
    int(digest, 16)  # ensures it's valid hex
