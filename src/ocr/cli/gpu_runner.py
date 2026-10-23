"""Compatibility launcher for unified single-document extraction."""
from ocr_pipeline.cli import main as _main


def main():
    return _main(False)


if __name__ == "__main__":
    raise SystemExit(main())
