"""Compatibility alias: this module moved to `ocr_document.manifest_exporter` (migration P08).

The object registered under this name is `ocr_document.manifest_exporter` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.manifest_exporter as _module

sys.modules[__name__] = _module
