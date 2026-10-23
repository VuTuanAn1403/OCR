"""Compatibility alias: this module moved to `ocr_document.output_contract` (migration P08).

The object registered under this name is `ocr_document.output_contract` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.output_contract as _module

sys.modules[__name__] = _module
