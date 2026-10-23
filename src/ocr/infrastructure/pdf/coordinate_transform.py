"""Compatibility alias: this module moved to `ocr_pdf_io.coordinate_transform` (migration P05b).

The object registered under this name is `ocr_pdf_io.coordinate_transform` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pdf_io.coordinate_transform as _module

sys.modules[__name__] = _module
