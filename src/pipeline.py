from pathlib import Path

from src.docx_processor import DocxProcessor


class DocumentPipeline:
    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)

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