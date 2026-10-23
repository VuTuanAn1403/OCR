"""Compatibility alias: this module moved to `ocr_recognition.ocr_layer_agreement` (migration P06).

The object registered under this name is `ocr_recognition.ocr_layer_agreement` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_recognition.ocr_layer_agreement as _module

sys.modules[__name__] = _module
