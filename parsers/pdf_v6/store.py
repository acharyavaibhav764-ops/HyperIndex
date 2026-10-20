"""Figure crops in MinIO.

Object names are derived from the *file content* (sha1 prefix), not from the upload's doc id,
because the parser runs before the id is known and the API layer stays untouched.  Same file ->
same keys -> re-ingesting overwrites instead of duplicating.  Chunks carry the ``s3://`` URL in
metadata (``figure_image``); presign it in the answer layer when the image should be shown.
"""
from __future__ import annotations


class FigureStore:
    def __init__(self, client, bucket: str, prefix: str = "figures") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    @classmethod
    def from_settings(cls, settings) -> "FigureStore":
        """Same MinIO endpoint/credentials as ``core.uploader.Uploader``."""
        import boto3  # deferred: the parser must import without boto3 configured

        client = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
        )
        return cls(client, settings.minio_bucket, getattr(settings, "pdf_figure_store_prefix", "figures"))

    def key(self, doc_key: str, figure_id: str) -> str:
        return f"{self.prefix}/{doc_key}/{figure_id}.png"

    def put(self, doc_key: str, figure_id: str, png: bytes) -> str:
        """Upload one crop; returns its ``s3://bucket/key`` URL (raises on failure)."""
        key = self.key(doc_key, figure_id)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=png, ContentType="image/png")
        return f"s3://{self.bucket}/{key}"
