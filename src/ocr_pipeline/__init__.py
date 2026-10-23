"""V6.3 orchestration on the CPU runtime: CLI, backend preparation, the
two-phase scheduler with its GPU lease, the per-document owner process, the
batch ledger and matrix publication, and analysis runs. Workers are started
as subprocesses by module name; nothing here imports Torch, VietOCR, ONNX
Runtime or Docling. Import submodules directly.
"""
