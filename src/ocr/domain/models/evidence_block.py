"""Compatibility alias: this module moved to `ocr_contracts.evidence_block` (migration P02).

The object registered under this name is `ocr_contracts.evidence_block` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.evidence_block as _module

sys.modules[__name__] = _module
