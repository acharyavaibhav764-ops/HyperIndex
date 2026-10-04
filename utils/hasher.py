import hashlib


def calculate_sha256(content: bytes) -> str:
    """Return the SHA-256 hexadecimal digest for file content."""
    return hashlib.sha256(content).hexdigest()
