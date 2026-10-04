import hashlib


def calculate_sha256(content: bytes) -> str:
    """Return the SHA-256 hexadecimal digest for file content."""
    return hashlib.sha256(content).hexdigest()


def documents_are_identical(first: bytes, second: bytes) -> bool:
    """Return whether two documents have identical raw bytes."""
    return calculate_sha256(first) == calculate_sha256(second)