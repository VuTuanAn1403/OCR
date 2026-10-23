"""Compatibility alias: this module moved to `ocr_pdf_io.scan_image` (migration P05b).

The object registered under this name is `ocr_pdf_io.scan_image` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pdf_io.scan_image as _module

sys.modules[__name__] = _module
