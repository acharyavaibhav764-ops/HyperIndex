"""S3-compatible object storage operations for MinIO."""

import logging
import os

import boto3
from botocore.exceptions import ClientError
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{MINIO_ENDPOINT}",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    region_name="us-east-1",
)


class StorageError(Exception):
    """Represent an expected object-storage failure."""

    def __init__(self, message, *, not_found=False):
        super().__init__(message)
        self.not_found = not_found


def create_bucket(bucket_name):
    """Create ``bucket_name`` when it does not already exist."""

    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code not in {"404", "NoSuchBucket", "NotFound"}:
            raise StorageError("Unable to check the storage bucket") from error
        try:
            s3.create_bucket(Bucket=bucket_name)
        except ClientError as create_error:
            raise StorageError("Unable to create the storage bucket") from create_error


def upload_to_minio(file, bucket_name):
    """Upload a FastAPI file to ``bucket_name``."""

    try:
        s3.upload_fileobj(file.file, bucket_name, file.filename)
    except ClientError as error:
        logger.exception("Object upload failed", extra={"filename": file.filename})
        raise StorageError("Unable to upload the document") from error


def get_document_metadata(bucket_name, filename):
    """Return metadata for ``filename`` from ``bucket_name``."""

    try:
        response = s3.head_object(Bucket=bucket_name, Key=filename)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NoSuchObject", "NotFound"}:
            raise StorageError("Document not found", not_found=True) from error
        raise StorageError("Unable to retrieve document metadata") from error

    return {
        "filename": filename,
        "content_type": response.get("ContentType"),
        "content_length": response.get("ContentLength"),
        "etag": response.get("ETag"),
        "last_modified": response.get("LastModified"),
        "metadata": response.get("Metadata", {}),
    }


