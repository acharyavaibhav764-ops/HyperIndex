"""Document upload service backed by MinIO's S3-compatible API."""

import logging
import os
from pathlib import PurePath
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Represent an expected object-storage failure."""


class DocumentService:
    """Coordinate document validation and storage in MinIO."""

    def __init__(self) -> None:
        """Configure the S3 client from the container environment."""
        endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
        self.bucket_name = os.getenv("MINIO_BUCKET", "honeywell-documents")
        self.client = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
            aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        """Create the configured bucket when it does not already exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError("Unable to check the document bucket") from error
            try:
                self.client.create_bucket(Bucket=self.bucket_name)
            except ClientError as create_error:
                raise StorageError("Unable to create the document bucket") from create_error

    def upload_documents(self, files: list[UploadFile]) -> list[dict[str, str]]:
        """Upload multiple documents and return their storage details."""
        documents: list[dict[str, str]] = []
        for file in files:
            filename = PurePath(file.filename or "").name
            if not filename:
                raise ValueError("Every uploaded document must have a filename")

            try:
                file.file.seek(0, 2)
                size = file.file.tell()
                file.file.seek(0)
            except (OSError, ValueError) as error:
                raise StorageError(f"Unable to read {filename}") from error
            if size == 0:
                raise ValueError(f"Document {filename} is empty")

            document_id = str(uuid4())
            object_key = document_id
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
                logger.exception("Document upload failed", extra={"filename": filename})
                raise StorageError(f"Unable to upload {filename}") from error

            logger.info("Upload successful | filename=%s | object_key=%s", filename, object_key)
            documents.append(
                {
                    "uuid": document_id,
                    "filename": filename,
                    "size": str(size),
                }
            )

        return documents

    def download_document(self, document_id: str) -> tuple[bytes, str]:
        """Download a stored document and recover its original filename when possible."""
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=document_id)
            content = response["Body"].read()
            response["Body"].close()
        except (ClientError, OSError) as error:
            raise StorageError(f"Unable to download document {document_id}") from error

        filename = response.get("Metadata", {}).get("filename", document_id)
        return content, filename