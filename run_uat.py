from pathlib import Path
import shutil

from src import blob_storage
from src.blob_storage import BlobStorageClient
from src.docx_processor import DocxProcessor
import json
from tqdm import tqdm

# ============================================================
# CONFIG
# ============================================================

# INPUT_CONTAINER = "test-input"
# OUTPUT_CONTAINER = "test-output"

WORK_DIR = Path("uat-work")
INPUT_DIR = WORK_DIR / "input"
OUTPUT_DIR = WORK_DIR / "output"


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 80)
    print("UAT DOCUMENT PIPELINE")
    print("=" * 80)

    # --------------------------------------------------------
    # 1. Prepare local directories
    # --------------------------------------------------------

    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # 2. Initialize Blob Storage
    # --------------------------------------------------------

    with open("local.settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)["Values"]

    connection_string = settings["AZURE_STORAGE_CONNECTION_STRING"]
    input_container = settings["AZURE_STORAGE_INPUT_CONTAINER"]
    output_container = settings["AZURE_STORAGE_OUTPUT_CONTAINER"]

    input_blob_storage = BlobStorageClient(
        connection_string=connection_string,
        container_name=input_container,
    )

    output_blob_storage = BlobStorageClient(
        connection_string=connection_string,
        container_name=output_container,
    )
    # --------------------------------------------------------
    # 3. List input DOCX
    # --------------------------------------------------------

    input_blobs = input_blob_storage.list_docx()

    print()
    print(f"Input DOCX files: {len(input_blobs)}")

    if not input_blobs:
        print("No DOCX files found in input container.")
        return

    # --------------------------------------------------------
    # 4. Download all input DOCX
    # --------------------------------------------------------

    downloaded_files = []

    print()
    print("=" * 80)
    print("DOWNLOAD INPUT FILES")
    print("=" * 80)

    for blob_name in input_blobs:
        local_file = INPUT_DIR / Path(blob_name).name

        print(f"Downloading: {blob_name}")

        input_blob_storage.download_blob(
            blob_name=blob_name,
            local_path=local_file,
        )

        downloaded_files.append(local_file)

    print(f"\n✓ Downloaded: {len(downloaded_files)} files")

    # --------------------------------------------------------
    # 5. Process all DOCX
    # --------------------------------------------------------

    processor = DocxProcessor()

    success_count = 0
    failed_count = 0

    print()
    print("=" * 80)
    print("PROCESS DOCX FILES")
    print("=" * 80)

    for input_file in tqdm(
        downloaded_files,
        desc="Processing",
        unit="file",
    ):
        output_file = (
            OUTPUT_DIR
            / f"{input_file.stem}.docx"
        )

        try:
            processor.process(
                input_path=input_file,
                output_path=output_file,
            )

            success_count += 1

        except Exception as e:
            failed_count += 1

            print(
                f"\n✗ Failed: {input_file.name}"
            )
            print(f"  Error: {e}")

    # --------------------------------------------------------
    # 6. Upload processed DOCX
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("UPLOAD OUTPUT FILES")
    print("=" * 80)

    uploaded_count = 0

    output_files = sorted(
        OUTPUT_DIR.glob("*.docx")
    )

    for output_file in output_files:
        blob_name = output_file.name

        print(
            f"Uploading: {output_file.name}"
        )

        output_blob_storage.upload_file(
            local_path=output_file,
            blob_name=blob_name,
            overwrite=True,
        )

        uploaded_count += 1

    # --------------------------------------------------------
    # 7. Summary
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("UAT SUMMARY")
    print("=" * 80)

    print(f"Input files       : {len(downloaded_files)}")
    print(f"Processed success : {success_count}")
    print(f"Processed failed  : {failed_count}")
    print(f"Uploaded files    : {uploaded_count}")

    print("=" * 80)

    if (
        failed_count == 0
        and uploaded_count == success_count
    ):
        print("✓ UAT PASSED")
    else:
        print("✗ UAT FAILED")


if __name__ == "__main__":
    main()