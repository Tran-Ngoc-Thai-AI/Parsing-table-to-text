from pathlib import Path
from typing import Any, Dict, List

from azure.storage.blob import BlobServiceClient

class BlobStorageClient:
    """
    Simple Azure Blob Storage client.

    Supports:
    - List blobs
    - List DOCX files
    - Download blob to local
    - Upload local file to blob
    """

    def __init__(
        self,
        connection_string: str,
        container_name: str,
    ):
        if not connection_string:
            raise ValueError("Azure Storage connection string is required.")

        if not container_name:
            raise ValueError("Blob container name is required.")

        self.container_name = container_name

        self.service_client = BlobServiceClient.from_connection_string(
            connection_string
        )

        self.container_client = self.service_client.get_container_client(
            container_name
        )

    def list_blobs(self, prefix: str = "") -> List[str]:
        """List blobs under a prefix."""

        blobs = self.container_client.list_blobs(
            name_starts_with=prefix
        )

        return [
            blob.name
            for blob in blobs
        ]

    def list_docx(self, prefix: str = "") -> List[str]:
        """List all DOCX blobs under a prefix."""

        blobs = self.list_blobs(prefix)

        return [
            blob_name
            for blob_name in blobs
            if blob_name.lower().endswith(".docx")
        ]

    def list_docx_metadata(self, prefix: str = "") -> List[dict]:
        """List DOCX blobs with blob properties and metadata."""

        blob_items = self.container_client.list_blobs(
            name_starts_with=prefix,
            include=["metadata"],
        )

        results = []

        for blob in blob_items:
            if not blob.name.lower().endswith(".docx"):
                continue

            results.append(
                {
                    "name": blob.name,
                    "etag": blob.etag,
                    "last_modified": blob.last_modified,
                    "size": blob.size,
                    "metadata": blob.metadata or {},
                }
            )

        return results

    def download_blob(
        self,
        blob_name: str,
        local_path: Path,
    ) -> Path:
        """Download one blob to local file."""

        local_path = Path(local_path)

        local_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        blob_client = self.container_client.get_blob_client(
            blob_name
        )

        with open(local_path, "wb") as file:
            download_stream = blob_client.download_blob()
            file.write(download_stream.readall())

        return local_path

    def upload_file(
        self,
        local_path: Path,
        blob_name: str,
        overwrite: bool = True,
        metadata: dict | None = None,
    ) -> str:
        """Upload one local file to Blob Storage."""

        local_path = Path(local_path)

        if not local_path.exists():
            raise FileNotFoundError(
                f"Local file not found: {local_path}"
            )

        blob_client = self.container_client.get_blob_client(
            blob_name
        )

        with open(local_path, "rb") as file:
            blob_client.upload_blob(
                file,
                overwrite=overwrite,
                metadata=metadata,
            )

        return blob_name

    def delete_blob(self, blob_name: str) -> None:
        """Delete one blob."""

        blob_client = self.container_client.get_blob_client(
            blob_name
        )

        blob_client.delete_blob()

if __name__ == "__main__":

    import json

    # ============================================================
    # Load settings
    # ============================================================

    with open("local.settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)["Values"]

    connection_string = settings["AZURE_STORAGE_CONNECTION_STRING"]
    input_container_name = settings["AZURE_STORAGE_INPUT_CONTAINER"]
    output_container_name = settings["AZURE_STORAGE_OUTPUT_CONTAINER"]

    if not connection_string:
        raise RuntimeError(
            "Missing AZURE_STORAGE_CONNECTION_STRING"
        )

    if not input_container_name:
        raise RuntimeError(
            "Missing AZURE_STORAGE_INPUT_CONTAINER"
        )

    if not output_container_name:
        raise RuntimeError(
            "Missing AZURE_STORAGE_OUTPUT_CONTAINER"
        )

    # ============================================================
    # TEST 1 — LIST
    # ============================================================

    print("=" * 80)
    print("TEST 1 — LIST DOCX")
    print("=" * 80)

    input_client = BlobStorageClient(
        connection_string=connection_string,
        container_name=input_container_name,
    )

    print(f"Container : {input_container_name}")
    print()

    docx_files = input_client.list_docx()

    print(f"Total DOCX: {len(docx_files)}")

    for blob_name in docx_files:
        print(f" - {blob_name}")

    if not docx_files:
        raise RuntimeError(
            "No DOCX files found in input container."
        )

    print()
    print("TEST 1 PASSED")

    # ============================================================
    # TEST 1B — LIST DOCX METADATA
    # ============================================================

    print()
    print("=" * 80)
    print("TEST 1B — LIST DOCX METADATA")
    print("=" * 80)

    docx_metadata = input_client.list_docx_metadata()

    print(f"Total DOCX: {len(docx_metadata)}")
    print()

    for item in docx_metadata:
        print(f"Blob name      : {item['name']}")
        print(f"ETag           : {item['etag']}")
        print(f"Last modified  : {item['last_modified']}")
        print(f"Size           : {item['size']} bytes")
        print("-" * 80)

    if len(docx_metadata) != len(docx_files):
        raise RuntimeError(
            "Metadata DOCX count does not match DOCX list count."
        )

    print("TEST 1B PASSED")

    # ============================================================
    # TEST 2 — DOWNLOAD ALL
    # ============================================================

    print()
    print("=" * 80)
    print("TEST 2 — DOWNLOAD ALL DOCX")
    print("=" * 80)

    local_dir = Path("test-data")
    local_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    downloaded_files = []

    for blob_name in docx_files:

        print(f"Downloading: {blob_name}")

        # Lấy tên file cuối cùng
        local_path = local_dir / Path(blob_name).name

        print(f"Source blob : {blob_name}")
        print(f"Local file  : {local_path}")

        input_client.download_blob(
            blob_name=blob_name,
            local_path=local_path,
        )

        if not local_path.exists():
            raise RuntimeError(
                f"Download failed: {local_path}"
            )

        downloaded_files.append(
            (blob_name, local_path)
        )

        print("Download OK")
        print()

    print(
        f"Downloaded files: {len(downloaded_files)}/{len(docx_files)}"
    )

    print("TEST 2 PASSED")

    # ============================================================
    # TEST 3 — UPLOAD ALL
    # ============================================================

    print()
    print("=" * 80)
    print("TEST 3 — UPLOAD ALL DOCX")
    print("=" * 80)

    output_client = BlobStorageClient(
        connection_string=connection_string,
        container_name=output_container_name,
    )

    uploaded_files = []

    for blob_name, local_path in downloaded_files:

        output_blob_name = local_path.name

        print(f"Uploading: {local_path}")
        print(f"Output blob : {output_blob_name}")
        print(f"Container   : {output_container_name}")

        output_client.upload_file(
            local_path=local_path,
            blob_name=output_blob_name,
        )

        uploaded_files.append(
            output_blob_name
        )

        print("Upload OK")
        print()

    # Verify all uploaded files
    output_files = output_client.list_docx()

    for output_blob_name in uploaded_files:

        if output_blob_name not in output_files:
            raise RuntimeError(
                f"Upload verification failed: {output_blob_name}"
            )

    print(
        f"Uploaded files: {len(uploaded_files)}/{len(downloaded_files)}"
    )

    print("TEST 3 PASSED")

    # ============================================================
    # TEST 4 — DELETE
    # ============================================================

    print()
    print("=" * 80)
    print("TEST 4 — DELETE BLOB")
    print("=" * 80)

    test_blob_name = "__test_delete_blob__.txt"

    print(f"Creating test blob: {test_blob_name}")

    test_blob_client = output_client.container_client.get_blob_client(
        test_blob_name
    )

    test_blob_client.upload_blob(
        b"test delete blob",
        overwrite=True,
    )

    # Verify test blob exists
    output_files_all = output_client.list_blobs()

    if test_blob_name not in output_files_all:
        raise RuntimeError(
            "Test blob was not created successfully."
        )

    print("Test blob created.")

    # Delete
    print(f"Deleting: {test_blob_name}")

    output_client.delete_blob(
        blob_name=test_blob_name
    )

    # Verify deleted
    output_files_all = output_client.list_blobs()

    if test_blob_name in output_files_all:
        raise RuntimeError(
            "Delete verification failed."
        )

    print("Delete verified.")
    print("TEST 4 PASSED")

    # ============================================================
    # FINAL RESULT
    # ============================================================

    print()
    print("=" * 80)
    print("ALL BLOB STORAGE TESTS PASSED")
    print("=" * 80)