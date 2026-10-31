"""Object storage for uploaded PDFs, behind a small interface (S3 API: SeaweedFS locally, R2)."""

import asyncio
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def read(self, key: str) -> bytes: ...


class S3Storage:
    """boto3 is blocking, so each call runs in a thread."""

    def __init__(
        self, *, endpoint_url: str, bucket: str, access_key: str, secret_key: str, region: str
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        """Create the bucket if it is missing (blocking; call it at startup)."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType="application/pdf",
        )

    def read_blocking(self, key: str) -> bytes:
        """For callers already on a worker thread (the ingestion worker)."""
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread(self.read_blocking, key)
