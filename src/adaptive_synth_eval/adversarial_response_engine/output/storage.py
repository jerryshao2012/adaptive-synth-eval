"""
Pluggable result storage backends.

Each backend implements write_json(local_path, data) -> uri.
The local_path is a Path relative to the project root; it also determines
the key/blob name for cloud backends.

Usage:
    storage = LocalStorage()
    storage = S3Storage(bucket="my-bucket", prefix="adversarial-eval")
    storage = AzureBlobStorage(container="results")  # conn string from env

    uri = storage.write_json(output_path, data_dict)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


class StorageBackend:
    def write_json(self, local_path: Path, data: Dict[str, Any]) -> str:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    def write_json(self, local_path: Path, data: Dict[str, Any]) -> str:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return str(local_path)


class S3Storage(StorageBackend):
    """
    Write results to AWS S3.

    Credentials resolved by boto3 (env vars, ~/.aws/credentials, or IAM role).

    Required env vars / args:
        AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY  (or IAM role)
        bucket   — target S3 bucket name
        prefix   — optional key prefix (e.g. "adversarial-eval/runs")
        region   — AWS region (default: us-east-1)
    """

    def __init__(self, bucket: str, prefix: str = "", region: str = "us-east-1"):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region = region

    def write_json(self, local_path: Path, data: Dict[str, Any]) -> str:
        try:
            import boto3
        except ImportError as e:
            raise ImportError("Install boto3: pip install boto3") from e

        s3 = boto3.client("s3", region_name=self.region)
        key_parts = [self.prefix, str(local_path)] if self.prefix else [str(local_path)]
        key = "/".join(p.strip("/") for p in key_parts)
        s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        return f"s3://{self.bucket}/{key}"


class AzureBlobStorage(StorageBackend):
    """
    Write results to Azure Blob Storage.

    Required env var (or pass connection_string= explicitly):
        AZURE_STORAGE_CONNECTION_STRING

    Required args:
        container   — blob container name
        prefix      — optional blob path prefix
    """

    def __init__(
            self,
            container: str,
            prefix: str = "",
            connection_string: str | None = None,
    ):
        self.container = container
        self.prefix = prefix.strip("/")
        self.connection_string = (
                connection_string or os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        )
        if not self.connection_string:
            raise ValueError(
                "Azure Blob Storage requires AZURE_STORAGE_CONNECTION_STRING env var "
                "or connection_string= argument."
            )

    def write_json(self, local_path: Path, data: Dict[str, Any]) -> str:
        try:
            from azure.storage.blob import BlobServiceClient, ContentSettings
        except ImportError as e:
            raise ImportError(
                "Install azure-storage-blob: pip install azure-storage-blob"
            ) from e

        blob_parts = [self.prefix, str(local_path)] if self.prefix else [str(local_path)]
        blob_name = "/".join(p.strip("/") for p in blob_parts)
        client = BlobServiceClient.from_connection_string(self.connection_string)
        blob_client = client.get_blob_client(container=self.container, blob=blob_name)
        blob_client.upload_blob(
            json.dumps(data, indent=2).encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        return f"azure-blob://{self.container}/{blob_name}"


def make_storage(
        backend: str = "local",
        *,
        s3_bucket: str = "",
        s3_prefix: str = "",
        s3_region: str = "us-east-1",
        azure_container: str = "",
        azure_prefix: str = "",
        azure_connection_string: str | None = None,
) -> StorageBackend:
    """
    Factory. backend is one of: local, s3, azure-blob.
    """
    if backend == "local":
        return LocalStorage()
    elif backend == "s3":
        if not s3_bucket:
            raise ValueError("--s3-bucket is required when --storage=s3")
        return S3Storage(bucket=s3_bucket, prefix=s3_prefix, region=s3_region)
    elif backend == "azure-blob":
        if not azure_container:
            raise ValueError("--azure-container is required when --storage=azure-blob")
        return AzureBlobStorage(
            container=azure_container,
            prefix=azure_prefix,
            connection_string=azure_connection_string,
        )
    else:
        raise ValueError(f"Unknown storage backend: {backend!r}. Use local, s3, or azure-blob.")
