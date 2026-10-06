import json

from src.blob_storage import BlobStorageClient
from src.pipeline import DocumentPipeline

import sys
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

SETTINGS_FILE = "local.settings.json"


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()



# ============================================================
# LOAD SETTINGS
# ============================================================

def load_settings():
    with open(
        SETTINGS_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)["Values"]


# ============================================================
# MAIN
# ============================================================

def main():
    logs_dir = Path("logs")
    logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_time = datetime.now()

    log_path = logs_dir / (
        f"pipeline_{run_time.strftime('%Y%m%d_%H%M%S')}.txt"
    )

    with open(
        log_path,
        "w",
        encoding="utf-8",
    ) as log_file:

        original_stdout = sys.stdout
        sys.stdout = Tee(
            original_stdout,
            log_file,
        )

        try:
            print("=" * 80)
            print("UAT DOCUMENT PIPELINE")
            print("=" * 80)

            settings = load_settings()

            connection_string = settings[
                "AZURE_STORAGE_CONNECTION_STRING"
            ]

            input_container = settings[
                "AZURE_STORAGE_INPUT_CONTAINER"
            ]

            output_container = settings[
                "AZURE_STORAGE_OUTPUT_CONTAINER"
            ]

            print()
            print(f"Input container  : {input_container}")
            print(f"Output container : {output_container}")

            input_blob_storage = BlobStorageClient(
                connection_string=connection_string,
                container_name=input_container,
            )

            output_blob_storage = BlobStorageClient(
                connection_string=connection_string,
                container_name=output_container,
            )

            pipeline = DocumentPipeline(
                input_dir=None,
                output_dir=None,
            )

            pipeline.sync_blobs(
                input_client=input_blob_storage,
                output_client=output_blob_storage,
            )

            print()
            print("=" * 80)
            print("UAT COMPLETED")
            print("=" * 80)

        finally:
            sys.stdout = original_stdout

    print()
    print(f"Log file: {log_path}")


if __name__ == "__main__":
    main()