"""Compatibility alias: this module moved to `ocr_artifacts.atomic_io` (migration P02).

The object registered under this name is `ocr_artifacts.atomic_io` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_artifacts.atomic_io as _module

sys.modules[__name__] = _module
