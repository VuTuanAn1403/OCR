"""Compatibility alias: this module moved to `ocr_recognition.routing_policy` (migration P06).

The object registered under this name is `ocr_recognition.routing_policy` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_recognition.routing_policy as _module

sys.modules[__name__] = _module
