"""Download the official VietOCR weights (vgg_seq2seq and v8 vgg_transformer)."""

import hashlib
import os
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
# Same lookup as VietnameseSeq2SeqEngine: VIETOCR_MODEL_DIR, else
# $OCR_MODELS_DIR/vietocr (e.g. a mounted Drive on Colab), else models/vietocr.
_MODELS_ROOT = Path(os.environ.get("OCR_MODELS_DIR") or ROOT / "models")
MODEL_DIR = Path(os.environ.get("VIETOCR_MODEL_DIR") or _MODELS_ROOT / "vietocr")
TRANSFORMER_DIR = _MODELS_ROOT / "v8" / "vietocr-vgg-transformer"

FILES = {
    "base.yml": "https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/base.yml",
    "vgg-seq2seq.yml": "https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/vgg-seq2seq.yml",
    "vgg_seq2seq.pth": "https://vocr.vn/data/vietocr/vgg_seq2seq.pth",
}
WEIGHT_SHA256 = "0921503a41375a0584268e23ef3d414ea478a8fe8777865c7745d38f2d0bc5db"

TRANSFORMER_FILES = {
    "base.yml": (
        "https://raw.githubusercontent.com/pbcquoc/vietocr/fe8c3a7fc714aec57ab81cec844eb3adf0c1636c/config/base.yml",
        "9c8283fadb950f06f5d3400475f80d5355700ff315c9c48b7875e6ea66647d1c",
    ),
    "vgg-transformer.yml": (
        "https://raw.githubusercontent.com/pbcquoc/vietocr/fe8c3a7fc714aec57ab81cec844eb3adf0c1636c/config/vgg-transformer.yml",
        "0df9feee197754c7381871e5dfd07c6f3e292a4853eece6f1af240923e57c907",
    ),
    "vgg_transformer.pth": (
        "https://vocr.vn/data/vietocr/vgg_transformer.pth",
        "380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_entries(model_dir: Path, entries: dict[str, tuple[str, str | None]]) -> None:
    """Download each pinned model asset into model_dir unless its hash already matches."""
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, (url, expected_sha256) in entries.items():
        target = model_dir / name
        if target.is_file() and (expected_sha256 is None or sha256(target) == expected_sha256):
            print(f"Ready: {target}")
            continue
        temporary = target.with_suffix(target.suffix + ".download")
        try:
            with urlopen(url, timeout=60) as response, temporary.open("wb") as destination:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    destination.write(chunk)
            if expected_sha256 is not None and sha256(temporary) != expected_sha256:
                raise ValueError(f"SHA256 mismatch: {name}")
            os.replace(temporary, target)
            print(f"Downloaded: {target}")
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    seq2seq_entries = {
        name: (url, WEIGHT_SHA256 if name == "vgg_seq2seq.pth" else None)
        for name, url in FILES.items()
    }
    _download_entries(MODEL_DIR, seq2seq_entries)
    _download_entries(TRANSFORMER_DIR, TRANSFORMER_FILES)


if __name__ == "__main__":
    main()
