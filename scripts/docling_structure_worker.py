"""JSON-line Docling worker entry; the implementation is ocr_workers.docling_server.

Kept at this path because the Docling client and packaged resources launch it
by file. The client puts the project code roots on PYTHONPATH.
"""
import runpy

if __name__ == "__main__":
    runpy.run_module("ocr_workers.docling_server", run_name="__main__", alter_sys=True)
