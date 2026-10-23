"""Compatibility alias: this module moved to `ocr_reporting.document_workbook` (migration P04).

The object registered under this name is `ocr_reporting.document_workbook` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_reporting.document_workbook as _module

sys.modules[__name__] = _module
