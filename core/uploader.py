import io
import logging
import re
from pathlib import PurePath
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile

from config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Represent object storage failure."""

    pass


def make_family_id(filename: str) -> str:
    """
    Derive a stable, URL-safe document-family slug from a filename.

    The slug is used as the second-level folder in the MinIO hierarchy:
        products/{product_id}/{family_id}/v{n}/{filename}

    A short random suffix ensures uniqueness across unrelated documents
    that happen to share a base name.
    """
    base = PurePath(filename).stem
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_").lower()[:60]
    return f"{slug}_{uuid4().hex[:6]}"


def build_storage_path(
    product_id: str, doc_family_id: str, version: int, filename: str
) -> str:
    """
    Return the hierarchical MinIO object key for a versioned document.

    Example:
        products/TC500/installation_manual_a8f3c1/v2/installation_manual_2024.pdf
    """
    return f"products/{product_id}/{doc_family_id}/v{version}/{filename}"


class Uploader:
    """MINIO interaction class for file storage.

    Attributes:
        bucket_name: Target bucket in MinIO
        client: S3 client

    Methods:
        ensure_bucket()
        upload_files()          – legacy flat-key upload (kept for compat)
        upload_file_bytes()     – versioned hierarchical upload
        download_file()
        delete_object()
    """

    def __init__(self, bucket_name: str | None = None) -> None:
        """Configure S3 client"""

        endpoint = settings.minio_endpoint
        self.bucket_name = bucket_name or settings.minio_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        """Create new bucket if it doesn't exist."""

        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError("Unable to check the file bucket") from error
            try:
                self.client.create_bucket(Bucket=self.bucket_name)
            except ClientError as create_error:
                raise StorageError("Unable to create the file bucket") from create_error

    def upload_files(self, files: list[UploadFile]) -> list[dict[str, Any]]:
        """Upload a list of files to MinIO with flat UUID keys (legacy path)."""

        uploaded_files: list[dict[str, Any]] = []
        for file in files:

            # Validate existence of filename
            filename = PurePath(file.filename or "").name
            if not filename:
                raise ValueError("Every uploaded file must have a filename")

            # Try reading the raw bytes of the file
            try:
                file.file.seek(0, 2)
                size = file.file.tell()
                file.file.seek(0)
            except (OSError, ValueError) as error:
                raise StorageError(f"Unable to read {filename}") from error
            if size == 0:
                raise ValueError(f"File {filename} is empty")

            # Attach relevant metadata and upload
            file_id = str(uuid4())
            object_key = file_id
            try:
                extra_args = {
                    "ContentType": file.content_type or "application/octet-stream",
                    "Metadata": {"filename": filename},
                }
                self.client.upload_fileobj(
                    file.file,
                    self.bucket_name,
                    object_key,
                    ExtraArgs=extra_args,
                )
            except (ClientError, OSError) as error:
                logger.exception("File upload failed", extra={"filename": filename})
                raise StorageError(f"Unable to upload {filename}") from error

            # Append file details to list
            logger.info("Upload successful | filename=%s | object_key=%s", filename, object_key)
            uploaded_files.append(
                {
                    "document_id": file_id,
                    "file_id": file_id,
                    "filename": filename,
                    "size_bytes": size,
                }
            )

        return uploaded_files

    def upload_file_bytes(
        self,
        content: bytes,
        object_key: str,
        filename: str,
        content_type: str = "application/octet-stream",
        extra_metadata: dict[str, str] | None = None,
    ) -> None:
        """
        Upload raw bytes directly to a hierarchical object key.

        S3 user-defined metadata values must be strings; all version/lineage
        data are coerced before being stored so the MinIO console can display
        them without further processing.

        Args:
            content:        Raw file bytes already in memory.
            object_key:     Full hierarchical key, e.g.
                            ``products/{pid}/{family}/v{n}/{filename}``
            filename:       Original filename stored in S3 metadata.
            content_type:   MIME type of the file.
            extra_metadata: Additional string key/value pairs to store as S3
                            object metadata (version, is_latest, etc.).
        """
        metadata: dict[str, str] = {"filename": filename, **(extra_metadata or {})}
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=content,
                ContentType=content_type,
                Metadata=metadata,
            )
        except (ClientError, OSError) as error:
            logger.exception("Versioned upload failed | key=%s", object_key)
            raise StorageError(f"Unable to upload {filename} to {object_key}") from error

        logger.info(
            "Versioned upload successful | key=%s | size=%d bytes",
            object_key,
            len(content),
        )

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        """Retrieve raw file bytes and original filename from MinIO."""

        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=file_id)
            content = response["Body"].read()
            response["Body"].close()
        except (ClientError, OSError) as error:
            raise StorageError(f"Unable to download file {file_id}") from error

        filename = response.get("Metadata", {}).get("filename", file_id)
        return content, filename

    def delete_object(self, object_key: str) -> None:
        """Delete a single object from MinIO by its full key."""

        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=object_key)
            logger.info("Deleted MinIO object | key=%s", object_key)
        except (ClientError, OSError) as error:
            logger.warning("Failed to delete MinIO object | key=%s | %s", object_key, error)
            raise StorageError(f"Unable to delete object {object_key}") from error
