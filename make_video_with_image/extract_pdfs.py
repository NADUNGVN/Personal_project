"""
extract_pdfs.py — Standalone utility to extract text from PDF files.

Dùng như một công cụ tiện ích độc lập (KHÔNG thuộc vào pipeline chính).
Pipeline chính (make_youtube_video.py) không yêu cầu PDF — chỉ cần tên topic.

Cách dùng:
    python extract_pdfs.py                          # Mặc định: input/pdf_content/ -> tmp_txt/
    python extract_pdfs.py --input custom_pdfs/     # Chỉ định thư mục PDF tùy chỉnh
    python extract_pdfs.py --output my_output/      # Chỉ định thư mục output tùy chỉnh
"""
import os
import sys
import glob
import argparse


def extract_pdfs(input_dir: str, output_dir: str):
    """Extract text from all PDF files in input_dir and save to output_dir."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("Error: PyMuPDF is not installed. Run: pip install pymupdf")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    pdfs = glob.glob(os.path.join(input_dir, "*.pdf"))

    if not pdfs:
        print(f"No PDF files found in: {input_dir}")
        return

    print(f"Found {len(pdfs)} PDF(s) in '{input_dir}'")

    for pdf_path in pdfs:
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()

            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            out_path = os.path.join(output_dir, f"{base_name}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"  ✅ Extracted: {os.path.basename(pdf_path)} → {out_path}")

        except Exception as e:
            print(f"  ❌ Failed to process {os.path.basename(pdf_path)}: {e}")

    print(f"\nDone. {len(pdfs)} file(s) processed → '{output_dir}'")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(base_dir, "input", "pdf_content")
    default_output = os.path.join(base_dir, "tmp_txt")

    parser = argparse.ArgumentParser(
        description="Extract text from PDF files (standalone utility, not part of main pipeline)."
    )
    parser.add_argument(
        "--input", "-i",
        default=default_input,
        help=f"Input directory containing PDF files (default: {default_input})"
    )
    parser.add_argument(
        "--output", "-o",
        default=default_output,
        help=f"Output directory for extracted .txt files (default: {default_output})"
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input directory does not exist: {args.input}")
        sys.exit(1)

    extract_pdfs(args.input, args.output)


if __name__ == "__main__":
    main()
