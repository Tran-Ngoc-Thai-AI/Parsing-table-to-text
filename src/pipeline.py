from pathlib import Path

from src.docx_processor import DocxProcessor


class DocumentPipeline:
    def __init__(
        self,
        input_dir: Path | None = None,
        output_dir: Path | None = None,
    ):
        self.input_dir = (
            Path(input_dir)
            if input_dir is not None
            else None
        )

        self.output_dir = (
            Path(output_dir)
            if output_dir is not None
            else None
        )

        if self.output_dir is not None:
            self.output_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

        self.processor = DocxProcessor()

    def get_input_files(self):
        """
        Get all DOCX files from input directory.
        """
        return sorted(
            self.input_dir.glob("*.docx")
        )

    def _get_output_blob_name(self, input_blob_name: str) -> str:
        """
        Map input blob path to output blob path.

        Example:
            input:
                folder-a/0001.docx

            output:
                folder-a/0001.docx
        """
        return input_blob_name

    def should_process(
        self,
        input_metadata: dict,
        output_metadata: dict | None,
    ) -> tuple[bool, str]:
        """
        Determine whether an input blob needs processing.

        Returns:
            (True, "NEW")
            (True, "MODIFIED")
            (False, "UNCHANGED")
        """

        if output_metadata is None:
            return True, "NEW"

        input_etag = input_metadata["etag"]

        output_source_etag = output_metadata.get(
            "metadata", {}
        ).get(
            "source_etag"
        )

        if input_etag != output_source_etag:
            return True, "MODIFIED"

        return False, "UNCHANGED"

    def sync_blobs(
        self,
        input_client,
        output_client,
    ):
        """
        Synchronize Azure Blob INPUT -> OUTPUT.

        Handles:
        - New files
        - Modified files
        - Unchanged files
        - Deleted files
        """

        input_files = input_client.list_docx_metadata()
        output_files = output_client.list_docx_metadata()

        input_map = {
            item["name"]: item
            for item in input_files
        }

        output_map = {
            item["name"]: item
            for item in output_files
        }

        new_count = 0
        modified_count = 0
        unchanged_count = 0
        deleted_count = 0
        failed_count = 0

        print()
        print("=" * 80)
        print("AZURE BLOB DOCUMENT PIPELINE")
        print("=" * 80)

        print(f"INPUT DOCX  : {len(input_files)}")
        print(f"OUTPUT DOCX : {len(output_files)}")

        # ========================================================
        # PROCESS NEW / MODIFIED / UNCHANGED
        # ========================================================

        for index, input_metadata in enumerate(
            input_files,
            start=1,
        ):
            input_blob_name = input_metadata["name"]

            output_blob_name = self._get_output_blob_name(
                input_blob_name
            )

            output_metadata = output_map.get(
                output_blob_name
            )

            should_process, status = self.should_process(
                input_metadata=input_metadata,
                output_metadata=output_metadata,
            )

            print()
            print("-" * 80)
            print(
                f"[{index}/{len(input_files)}] "
                f"{input_blob_name}"
            )
            print(f"Status: {status}")

            if not should_process:
                unchanged_count += 1

                print("→ SKIP")
                continue

            try:
                if status == "NEW":
                    new_count += 1
                elif status == "MODIFIED":
                    modified_count += 1

                print("→ PROCESS")

                # ------------------------------------------------
                # Temporary local paths
                # ------------------------------------------------

                local_input = (
                    Path("temp") / input_blob_name
                )

                local_output = (
                    Path("temp_processed") / input_blob_name
                )

                # ------------------------------------------------
                # Download
                # ------------------------------------------------

                input_client.download_blob(
                    blob_name=input_blob_name,
                    local_path=local_input,
                )

                # ------------------------------------------------
                # Process DOCX
                # ------------------------------------------------

                self.processor.process(
                    input_path=local_input,
                    output_path=local_output,
                )

                # ------------------------------------------------
                # Upload OUTPUT
                # ------------------------------------------------

                output_metadata = dict(
                    input_metadata.get("metadata", {})
                )

                output_metadata["source_etag"] = input_metadata["etag"]

                output_client.upload_file(
                    local_path=local_output,
                    blob_name=output_blob_name,
                    overwrite=True,
                    metadata=output_metadata,
                )

                print(
                    f"✓ Uploaded: {output_blob_name}"
                )

                # Cleanup temporary files after successful upload
                if local_input.exists():
                    local_input.unlink()

                if local_output.exists():
                    local_output.unlink()

            except Exception as e:
                failed_count += 1

                print(
                    f"✗ Failed: {input_blob_name}"
                )
                print(f"  Error: {e}")

        # ========================================================
        # DELETE OUTPUTS WHOSE INPUT WAS DELETED
        # ========================================================

        for output_blob_name in output_map:

            if output_blob_name not in input_map:

                print()
                print("-" * 80)
                print(
                    f"DELETED INPUT → DELETE OUTPUT: "
                    f"{output_blob_name}"
                )

                try:
                    output_client.delete_blob(
                        blob_name=output_blob_name
                    )

                    deleted_count += 1

                    print(
                        f"✓ Deleted: {output_blob_name}"
                    )

                except Exception as e:
                    failed_count += 1

                    print(
                        f"✗ Delete failed: "
                        f"{output_blob_name}"
                    )
                    print(f"  Error: {e}")

        # ========================================================
        # SUMMARY
        # ========================================================

        print()
        print("=" * 80)
        print("AZURE BLOB PIPELINE SUMMARY")
        print("=" * 80)

        print(f"New       : {new_count}")
        print(f"Modified  : {modified_count}")
        print(f"Unchanged : {unchanged_count}")
        print(f"Deleted   : {deleted_count}")
        print(f"Failed    : {failed_count}")

        print("=" * 80)

    def process_all(self):
        """
        Process all DOCX files in input directory.
        """
        input_files = self.get_input_files()

        print("=" * 80)
        print("DOCUMENT PIPELINE")
        print("=" * 80)

        print(f"Input directory : {self.input_dir.resolve()}")
        print(f"Output directory: {self.output_dir.resolve()}")
        print(f"DOCX files      : {len(input_files)}")

        if not input_files:
            print("\nNo DOCX files found.")
            return

        success_count = 0
        failed_count = 0

        for index, input_file in enumerate(input_files, start=1):
            output_file = (
                self.output_dir
                / f"{input_file.stem}.docx"
            )

            print()
            print("=" * 80)
            print(
                f"[{index}/{len(input_files)}] "
                f"{input_file.name}"
            )
            print("=" * 80)

            try:
                self.processor.process(
                    input_path=input_file,
                    output_path=output_file,
                )

                success_count += 1

                print(
                    f"✓ Completed: {output_file.name}"
                )

            except Exception as e:
                failed_count += 1

                print(
                    f"✗ Failed: {input_file.name}"
                )
                print(f"  Error: {e}")

        print()
        print("=" * 80)
        print("PIPELINE SUMMARY")
        print("=" * 80)
        print(f"Total files : {len(input_files)}")
        print(f"Success     : {success_count}")
        print(f"Failed      : {failed_count}")
        print("=" * 80)


if __name__ == "__main__":
    INPUT_DIR = Path("input")
    OUTPUT_DIR = Path("output")

    pipeline = DocumentPipeline(
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR,
    )

    pipeline.process_all()