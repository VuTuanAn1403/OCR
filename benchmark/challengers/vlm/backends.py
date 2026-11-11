"""Local VLM backends, gated by the model catalog (V8-043) and a pin file before anything is loaded.

A backend may load a model only:

* for a catalog VLM candidate whose ``download_allowed`` holds (licences VERIFIED, revision
  pinned, weights sha256 recorded);
* when ``pins/<candidate>.json`` names the same revision and weights sha256 as the catalog;
* from a local directory whose files all match the pin: git blob sha1 for code, config and
  tokenizer files, sha256 for LFS weights. The custom model code that ``trust_remote_code``
  executes is therefore exactly the code of the pinned revision.

Nothing is downloaded here; the user downloads with the pin's ``download_command``. Model
code from the repository runs only when the user starts a run themselves.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Dict, Optional

from benchmark.challengers import catalog

CATALOG = Path(__file__).resolve().parents[1] / "model_catalog.json"
PINS = Path(__file__).resolve().parent / "pins"
OPTIONAL_FILES = ("README.md", ".gitattributes")


class BackendUnavailable(RuntimeError):
    pass


def candidate(candidate_id: str, catalog_path: Path = CATALOG) -> Dict:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    for entry in data["candidates"]:
        if entry["id"] == candidate_id:
            if entry.get("experiment_layer") != "VLM":
                raise BackendUnavailable(f"{candidate_id} is not a VLM candidate")
            return entry
    raise BackendUnavailable(f"{candidate_id} is not in the catalog")


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_local(weights_dir: Path, pin: Dict) -> Dict:
    """Every pinned file present and identical; returns what was checked."""
    problems, checked = [], 0
    for name, expected in pin["files"].items():
        path = weights_dir / name
        if not path.is_file():
            if name not in OPTIONAL_FILES:
                problems.append(f"missing {name}")
            continue
        if path.stat().st_size != expected["size"]:
            problems.append(f"{name}: size {path.stat().st_size} != {expected['size']}")
            continue
        found = sha256_file(path) if "sha256" in expected else git_blob_sha1(path.read_bytes())
        if found != expected.get("sha256", expected["git_oid"]):
            problems.append(f"{name}: hash differs from revision {pin['revision'][:12]}")
        checked += 1
    if problems:
        raise BackendUnavailable("local files do not match the pin: " + "; ".join(problems[:8]))
    return {"files_checked": checked, "revision": pin["revision"]}


def open_backend(candidate_id: str, weights_dir: Path, catalog_path: Path = CATALOG, pins_dir: Path = PINS,
                 factory: Optional[Callable[[Path, Dict], object]] = None):
    entry = candidate(candidate_id, catalog_path)
    if not catalog.download_allowed(entry):
        raise BackendUnavailable(f"{candidate_id}: catalog does not allow use: {catalog.download_blockers(entry)}")
    pin_path = pins_dir / f"{candidate_id}.json"
    if not pin_path.is_file():
        raise BackendUnavailable(f"{candidate_id}: no pin file {pin_path}")
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    weights = [name for name, item in pin["files"].items() if "sha256" in item]
    if pin["revision"] != entry["revision"] or [pin["files"][name]["sha256"] for name in weights] != [entry["weights_sha256"]]:
        raise BackendUnavailable(f"{candidate_id}: pin and catalog disagree on revision or weights sha256")
    if not weights_dir.is_dir():
        raise BackendUnavailable(f"{weights_dir} does not exist; weights are never downloaded by the adapter "
                                 f"(download with: {pin.get('download_command')})")
    verify_local(weights_dir, pin)
    if factory is not None:
        return factory(weights_dir, pin)
    if candidate_id == "vintern-1b-v3.5":
        return VinternBackend(weights_dir, pin)
    raise BackendUnavailable(f"{candidate_id}: no inference code is written for this model yet")


# ---- Vintern-1B-v3.5 (InternVL2.5-1B fine-tune), following its model card --------------------------

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
TILE = 448


def tile_grid(width: int, height: int, min_num: int = 1, max_num: int = 6) -> tuple:
    """Columns and rows of 448 px tiles closest to the page aspect ratio (model card dynamic_preprocess)."""
    ratios = sorted({(i, j) for n in range(min_num, max_num + 1) for i in range(1, n + 1) for j in range(1, n + 1)
                     if min_num <= i * j <= max_num}, key=lambda r: r[0] * r[1])
    aspect, best, best_diff = width / height, (1, 1), float("inf")
    for ratio in ratios:
        diff = abs(aspect - ratio[0] / ratio[1])
        if diff < best_diff:
            best, best_diff = ratio, diff
        elif diff == best_diff and width * height > 0.5 * TILE * TILE * ratio[0] * ratio[1]:
            best = ratio
    return best


class VinternBackend:
    """bf16 on CUDA; greedy decoding without a repetition penalty, so repeated digits are not discouraged."""

    engine = "vintern-1b-v3.5"

    def __init__(self, weights_dir: Path, pin: Dict, max_tiles: int = 6, max_new_tokens: int = 2048):
        import torch
        from transformers import AutoModel, AutoTokenizer

        if not torch.cuda.is_available():
            raise BackendUnavailable("CUDA is required (AGENTS.md: GPU only for model runs)")
        self.torch = torch
        self.max_tiles = max_tiles
        self.generation = {"max_new_tokens": max_new_tokens, "do_sample": False, "num_beams": 1, "repetition_penalty": 1.0}
        self.model_version = f"{pin['repository']}@{pin['revision']}"
        self.model = AutoModel.from_pretrained(str(weights_dir), torch_dtype=torch.bfloat16, low_cpu_mem_usage=True,
                                               trust_remote_code=True, use_flash_attn=False, local_files_only=True).eval().cuda()
        self.tokenizer = AutoTokenizer.from_pretrained(str(weights_dir), trust_remote_code=True, use_fast=False,
                                                       local_files_only=True)

    def pixels(self, image_png: bytes):
        import io

        import torchvision.transforms as T
        from PIL import Image
        from torchvision.transforms.functional import InterpolationMode

        image = Image.open(io.BytesIO(image_png)).convert("RGB")
        columns, rows = tile_grid(*image.size, max_num=self.max_tiles)
        resized = image.resize((TILE * columns, TILE * rows))
        tiles = [resized.crop((c * TILE, r * TILE, (c + 1) * TILE, (r + 1) * TILE)) for r in range(rows) for c in range(columns)]
        if len(tiles) > 1:
            tiles.append(image.resize((TILE, TILE)))
        transform = T.Compose([T.Resize((TILE, TILE), interpolation=InterpolationMode.BICUBIC), T.ToTensor(),
                               T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD)])
        return self.torch.stack([transform(tile) for tile in tiles]).to(self.torch.bfloat16).cuda()

    def transcribe(self, image_png: bytes, prompt: str) -> str:
        try:
            with self.torch.inference_mode():
                return self.model.chat(self.tokenizer, self.pixels(image_png), "<image>\n" + prompt, self.generation)
        except self.torch.cuda.OutOfMemoryError:
            self.torch.cuda.empty_cache()
            raise
