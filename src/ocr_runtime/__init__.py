"""Runtime support shared by the CPU pipeline and both GPU workers: project
paths and resources, profile configuration, model registry, code
fingerprints, dependency locks, GPU lease, process-tree supervision, device
placement audits and preflight.

Importing this package imports none of its submodules: the Docling worker
loads `dependency_lock` and `torch_placement` without PyYAML or psutil.
"""
