import logging
import os
from pathlib import PurePath
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Represent object storage failure."""

    pass


class Uploader:
    """MINIO interaction class for file storage:

    Attributes:
        bucket_name: Target bucket in MinIO
        client: S3 client
    """

    def __init__(self) -> None:
        endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
        self.bucket_name = os.getenv("MINIO_BUCKET", "honeywell-files")
        self.client = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
            aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        """Check for existence of bucket, else create it."""
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

    def upload_files(self, files: list[UploadFile]) -> list[dict[str, str]]:
        """Upload a list of files to MinIO and return their metadata."""
        uploaded_files: list[dict[str, str]] = []
        for file in files:
            filename = PurePath(file.filename or "").name
            if not filename:
                raise ValueError("Every uploaded file must have a filename")

            try:
                file.file.seek(0, 2)
                size = file.file.tell()
                file.file.seek(0)
            except (OSError, ValueError) as error:
                raise StorageError(f"Unable to read {filename}") from error
            if size == 0:
                raise ValueError(f"File {filename} is empty")

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

            logger.info("Upload successful | filename=%s | object_key=%s", filename, object_key)
            uploaded_files.append(
                {
                    "uuid": file_id,
                    "filename": filename,
                    "size": str(size),
                }
            )

        return uploaded_files

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
