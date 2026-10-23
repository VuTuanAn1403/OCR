"""Wheel layout and runtime resources (P10).

The `ocr_*` packages install top-level from `src/`. The legacy namespace
`src.ocr` (frozen legacy code and aliases of moved modules, D2) stays
installable under its old name as a transitional exception, until nothing
imports `src.ocr`; `benchmark` keeps the `ocrpdf-perf` entry point. Runtime
files are copied at build time from their single authoritative source into
`ocr_runtime/resources`, never maintained separately.
"""
from pathlib import Path
from shutil import copyfile

from setuptools import find_namespace_packages, find_packages, setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
RESOURCES = "ocr_runtime/resources"
BUNDLES = {
    "keywords.txt": "config/keywords.txt",
    "profiles.yaml": "config/profiles.yaml",
    "profiles-v63.yaml": "config/profiles-v63.yaml",
    "docling_structure_worker.py": "scripts/docling_structure_worker.py",
    "fonts/NotoSans-Regular.ttf": "assets/fonts/NotoSans-Regular.ttf",
    "fonts/OFL.txt": "assets/fonts/OFL.txt",
    **{f"hardware/{path.name}": f"config/hardware/{path.name}"
       for path in sorted((ROOT / "config/hardware").glob("*.yaml"))},
}
PACKAGES = (find_packages("src", include=["ocr_*"])
            + ["src"] + [f"src.{name}" for name in find_packages("src", include=["ocr", "ocr.*"])]
            + find_namespace_packages(".", include=["benchmark", "benchmark.*"]))


class BuildRuntimeResources(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / RESOURCES
        for name, source in BUNDLES.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            copyfile(ROOT / source, target / name)

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + [
            str(Path(self.build_lib) / RESOURCES / name) for name in BUNDLES
        ]


setup(packages=PACKAGES, cmdclass={"build_py": BuildRuntimeResources})
