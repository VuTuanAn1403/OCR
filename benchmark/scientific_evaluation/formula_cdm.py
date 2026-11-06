"""Auditable CPU adapter for rendered formula comparison, without PDF OCR.

CDM tokenization, coloring and matching come from the pinned Apache-2.0
UniMERNet sources in _vendor. This adapter uses PyMuPDF at 200 dpi instead of
ImageMagick/Ghostscript. Its results are a named variant, not a claim of renderer
parity or independent ground truth. Release acceptance remains separately gated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import unicodedata

SCHEMA = "formula-cdm-variant-v1"
LEGACY_METHOD = "unimernet-cdm-5a2c80d-pymupdf200-aa0-tol1-v1"
METHOD = "unimernet-cdm-5a2c80d-pymupdf200-aa0-tol1-unicode-v2"
TEX_ENGINES = {LEGACY_METHOD: "pdflatex", METHOD: "lualatex"}
UNICODE_FONTS = ("lmroman12-regular.otf", "latinmodern-math.otf")
# Plain math character equivalents under unicode-math. Do not use NFKC or
# fold Latin lookalikes, Greek variants, or other changes in numeric content.
UNICODE_MATH_ALIASES = {
    "-": "−",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ϵ", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ", r"\varkappa": "ϰ",
    r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\varpi": "ϖ",
    r"\rho": "ρ", r"\varrho": "ϱ", r"\sigma": "σ", r"\varsigma": "ς", r"\tau": "τ", r"\upsilon": "υ",
    r"\phi": "ϕ", r"\varphi": "φ", r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ", r"\Xi": "Ξ", r"\Pi": "Π",
    r"\Sigma": "Σ", r"\Upsilon": "Υ", r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
}
VENDOR = Path(__file__).resolve().parent / "_vendor/unimernet_cdm"
VENDOR_MANIFEST_SHA256 = "02b700d989aadece5926d19509458d6b3b1ddd10caa8460496f5d7dbfa35a5fb"
MAX_CHARACTERS = 16_384
MAX_TOKENS = 2_048
MAX_PROCESS_OUTPUT = 2_000_000
MAX_PAIR_FILE_BYTES = 32 * 1024 * 1024
PACKAGES = ("numpy", "scipy", "scikit-image", "Pillow", "PyMuPDF")
FORBIDDEN_COMMAND = re.compile(
    r"\\(?:input|include|includeonly|usepackage|documentclass|write\d*|openout|openin|read\d*|"
    r"immediate|special|directlua|latelua|lua\w*|pdf\w*|catcode|csname|endcsname|def|gdef|edef|xdef|"
    r"newcommand|renewcommand|let|futurelet|loop|repeat|every\w*|file\w*|scantokens|"
    r"makeatletter|makeatother|endinput|shipout|output|font|jobname)\b", re.I
)
TEMPLATE = r"""\documentclass[12pt]{article}
\usepackage[landscape]{geometry}
\geometry{a<PAPER>paper,scale=0.98}
\pagestyle{empty}
\usepackage{booktabs,amsmath,upgreek,amssymb,xcolor}
\begin{document}
\makeatletter
\renewcommand*{\@textcolor}[3]{\protect\leavevmode\begingroup\color#1{#2}#3\endgroup}
\makeatother
\begin{displaymath}
<FORMULA>
\end{displaymath}
\end{document}
"""
UNICODE_SETUP = r"""\usepackage{unicode-math}
\setmainfont{lmroman12-regular.otf}
\setmathfont{latinmodern-math.otf}
\tracinglostchars=3
"""


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _read_json(path):
    def unique_fields(items):
        value = dict(items)
        _require(len(value) == len(items), f"Duplicate JSON keys in {path}")
        return value

    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_PAIR_FILE_BYTES + 1)
    _require(len(raw) <= MAX_PAIR_FILE_BYTES, "Formula JSON exceeds the input limit")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_fields), hashlib.sha256(raw).hexdigest()


def _write(path, payload):
    with Path(path).open("xb") as stream:
        stream.write(_json_bytes(payload))


def verify_vendor():
    raw = (VENDOR / "PROVENANCE.json").read_bytes()
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    _require(manifest_sha256 == VENDOR_MANIFEST_SHA256, "Pinned CDM manifest changed")
    manifest = json.loads(raw)
    for row in manifest["files"]:
        path = (VENDOR / row["path"]).resolve()
        _require(path.is_relative_to(VENDOR) and _sha(path) == row["sha256"],
                 f"Pinned CDM source changed: {row['path']}")
    return {"revision": manifest["revision"], "manifest_sha256": manifest_sha256,
            "verified_files": len(manifest["files"])}


def _run(argv, directory, stem, *, input_text=None, timeout=30, env=None):
    """Run explicit argument vectors and terminate the owned tree on timeout."""
    stdout, stderr = directory / f"{stem}.stdout", directory / f"{stem}.stderr"
    started = time.monotonic()
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    timed_out = False
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = subprocess.Popen([str(value) for value in argv], cwd=directory,
                                   stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                   stdout=out, stderr=err, env=env, shell=False, **flags)
        try:
            process.communicate(None if input_text is None else input_text.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                killer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
                subprocess.run([str(killer), "/PID", str(process.pid), "/T", "/F"],
                               stdout=err, stderr=err, check=False, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
    return {"argv": [str(value) for value in argv], "returncode": process.returncode,
            "timed_out": timed_out, "seconds": time.monotonic() - started,
            "stdout": stdout.name, "stdout_sha256": _sha(stdout),
            "stderr": stderr.name, "stderr_sha256": _sha(stderr),
            "output_limit_exceeded": max(stdout.stat().st_size, stderr.stat().st_size) > MAX_PROCESS_OUTPUT}


def runtime_identity(node, pdflatex, directory, lualatex=None):
    """Observe executable bytes, versions and Python packages; no installation."""
    _require((pdflatex is None) != (lualatex is None), "Supply exactly one TeX executable")
    vendor = verify_vendor()
    tools = {}
    method = METHOD if lualatex is not None else LEGACY_METHOD
    executables = {"node": node, TEX_ENGINES[method]: lualatex if lualatex is not None else pdflatex}
    for name, value in executables.items():
        path = Path(value).resolve(strict=True)
        _require(path.is_file() and path.suffix.lower() not in (".bat", ".cmd", ".ps1"),
                 "Formula tools must be explicit native executable paths")
        result = _run([path, "--version"], directory, f"version-{name}", timeout=15)
        _require(result["returncode"] == 0 and not result["timed_out"] and not result["output_limit_exceeded"],
                 f"Cannot identify formula tool: {name}")
        tools[name] = {"path": str(path), "sha256": _sha(path),
                       "adjacent_dlls": [{"name": file.name, "sha256": _sha(file)} for file in sorted(path.parent.glob("*.dll"))],
                       "version": (directory / result["stdout"]).read_text(encoding="utf-8", errors="replace").strip(),
                       "probe": result}
    runtime = {"method": method, "vendor": vendor, "tools": tools,
            "python": {"version": sys.version, "executable": sys.executable, "sha256": _sha(sys.executable)},
            "packages": {name: importlib.metadata.version(name) for name in PACKAGES},
            "adapter_sha256": _sha(__file__), "dpi": 200, "antialias_bits": 0, "color_tolerance_rgb": 1,
            "limits": {"characters": MAX_CHARACTERS, "tokens": MAX_TOKENS, "process_seconds": 30},
            "identity_scope": "Adapter, pinned vendor, observed executable bytes and package versions; used TeX inputs are recorded per render. Not a full OS fingerprint."}
    if lualatex is not None:
        lookup = Path(lualatex).absolute().with_name("kpsewhich.exe" if os.name == "nt" else "kpsewhich")
        probe = _run([lookup, "-progname=lualatex", *UNICODE_FONTS], directory, "unicode-fonts", timeout=15)
        _require(probe["returncode"] == 0 and not probe["timed_out"] and not probe["output_limit_exceeded"],
                 "Cannot locate the required Unicode renderer fonts")
        paths = [Path(line).resolve(strict=True) for line in
                 (directory / probe["stdout"]).read_text(encoding="utf-8").splitlines()]
        _require([path.name for path in paths] == list(UNICODE_FONTS), "Unexpected Unicode renderer fonts")
        runtime["unicode_fonts"] = {path.name: {"path": str(path), "sha256": _sha(path)} for path in paths}
    return runtime


def runtime_signature(runtime):
    """Compare observed runtime identities independently of probe paths and durations."""
    tools = {name: {key: runtime["tools"][name][key] for key in ("sha256", "adjacent_dlls", "version")}
             for name in ("node", TEX_ENGINES[runtime["method"]])}
    return {**{key: runtime[key] for key in ("method", "vendor", "packages", "adapter_sha256", "dpi", "antialias_bits",
                                          "color_tolerance_rgb", "limits")}, "tools": tools,
            "python": {key: runtime["python"][key] for key in ("version", "sha256")},
            "unicode_fonts": {name: entry["sha256"] for name, entry in runtime.get("unicode_fonts", {}).items()}}


def _tokenize(raw, node, directory):
    # Preserve the source bytes separately. These are the reference wrapper's
    # math environment and percent protections, without shell pipes or fallback.
    value = raw.replace("\r", " ").replace("\n", " ").replace(r"\%", "<PERCENTAGETOKEN>")
    value = re.sub(r"\\begin{(split|align|alignedat|alignat|eqnarray)\*?}(.+?)\\end{\1\*?}",
                   r"\\begin{aligned}\2\\end{aligned}", value, flags=re.S)
    value = re.sub(r"\\begin{smallmatrix\*?}(.+?)\\end{smallmatrix\*?}",
                   r"\\begin{matrix}\1\\end{matrix}", value, flags=re.S)
    result = _run([node, VENDOR / "tokenize_latex/preprocess_formula.js", "normalize"], directory,
                  "tokenize", input_text=value + "\n")
    if result["returncode"] or result["timed_out"] or result["output_limit_exceeded"]:
        return None, result
    output = (directory / result["stdout"]).read_text(encoding="utf-8", errors="strict")
    # The upstream JS catches parse errors and still exits 0. Blank output or
    # stderr is a failed tokenization, never a reason to render a fallback.
    if (directory / result["stderr"]).stat().st_size or len(output.splitlines()) != 1 or not output.strip():
        return None, result
    operators = ("arccos", "arcsin", "arctan", "arg", "cos", "cosh", "cot", "coth", "csc", "deg", "det",
                 "dim", "exp", "gcd", "hom", "inf", "injlim", "ker", "lg", "lim", "liminf", "limsup", "ln",
                 "log", "max", "min", "Pr", "projlim", "sec", "sin", "sinh", "sup", "tan", "tanh")
    pattern = r"\\operatorname {(" + "|".join(" ".join(word) for word in operators) + r")}"
    output = re.sub(pattern, lambda match: "\\" + match[1].replace(" ", ""), output.strip())
    return output.replace(r"\\ \end{array}", r"\end{array}").replace("< P E R C E N T A G E T O K E N >", r"\%"), result


def _tokenizer_error(directory, process):
    log = (directory / process["stderr"]).read_text(encoding="utf-8", errors="replace")
    # This pinned parser predates several valid commands and Unicode forms.
    # Only recognized grammar errors for the supported subset can be scored.
    if re.search(r"^ParseError: KaTeX parse error: (?:Expected group after '\\(?:frac|dfrac|tfrac|binom)'|Expected '}', got 'EOF')(?: at position |$)",
                 log, re.M):
        return "CONTENT_RENDER_FAILURE"
    return "TOKENIZER_UNSUPPORTED_OR_FAILED"


def _colored(value):
    from ._vendor.unimernet_cdm.latex_processor import normalize_latex, token_add_color_RGB

    normalized = normalize_latex(value)
    parts, tokens, index = normalized.strip().split(" "), [], 0
    _require(len(parts) <= MAX_CHARACTERS, "Normalized formula exceeds the preprocessing limit")
    while index < len(parts):
        previous = index
        parts, index, tokens = token_add_color_RGB(parts, index, tokens)
        _require(index > previous and len(tokens) <= MAX_TOKENS, "Formula exceeds the colored-token limit")
    value, colors = " ".join(parts), []
    for index in range(len(tokens)):
        color_id = index + 1
        color = ((color_id // 18**2) * 15, ((color_id % 18**2) // 18) * 15, (color_id % 18) * 15)
        colors.append(color)
        value = value.replace(f"<color_{index}>", ",".join(str(channel) for channel in color))
    paper = 3 if len(tokens) > 1300 else 4 if len(tokens) > 600 else 5
    return TEMPLATE.replace("<PAPER>", str(paper)).replace("<FORMULA>", value), normalized, tokens, colors


def _tex_inputs(directory, unicode_fonts=None):
    path = directory / "formula.fls"
    _require(path.is_file(), "TeX did not produce its input recorder")
    files = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("INPUT "):
            source = Path(line[6:].strip('"'))
            source = (directory / source).resolve() if not source.is_absolute() else source.resolve()
            _require(source.is_file(), f"TeX input disappeared: {source}")
            files[str(source)] = _sha(source)
    _require(bool(files), "TeX input recorder was empty")
    if unicode_fonts is not None:
        log = (directory / "formula.log").read_text(encoding="utf-8", errors="replace")
        # LuaTeX lists embedded OpenType fonts in its log, not in .fls.
        embedded = [Path(name).resolve(strict=True) for name in re.findall(r"<([^<>\r\n]+\.otf)>", log)]
        _require(bool(embedded), "Unicode TeX render did not record embedded fonts")
        for font in embedded:
            digest = _sha(font)
            if font.name in unicode_fonts:
                _require(digest == unicode_fonts[font.name]["sha256"], "Embedded Unicode font differs from runtime")
            files[str(font)] = digest
    return [{"path": path, "sha256": digest} for path, digest in sorted(files.items())]


def _glyphs(directory, tokens, colors):
    import numpy as np
    from PIL import Image
    import pymupdf

    with pymupdf.open(directory / "formula.pdf") as pdf:
        _require(len(pdf) == 1, "Formula rendered across multiple pages")
        levels = pymupdf.TOOLS.show_aa_level()
        _require(levels["text"] == levels["graphics"], "Use an isolated renderer with equal text/graphics AA levels")
        try:
            # Thin relation/fraction strokes can have no solid color pixels
            # with antialiasing. Do not silently lose them from denominators.
            pymupdf.TOOLS.set_aa_level(0)
            pixmap = pdf[0].get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False)
        finally:
            pymupdf.TOOLS.set_aa_level(levels["text"])
        pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
        ys, xs = np.where(np.any(pixels != 255, axis=2))
        _require(len(xs) > 0, "Formula render has no visible pixels")
        # Match the reference's exclusive crop bounds and eight-pixel pad.
        crop = (int(xs.min()) - 8, int(ys.min()) - 8, int(xs.max()) + 8, int(ys.max()) + 8)
        image = Image.fromarray(pixels).crop(crop)
    image.save(directory / "colored.png")
    pixels = np.asarray(image).astype(np.int16)
    rows = []
    for token, color in zip(tokens, colors):
        # MuPDF maps xcolor's five-decimal PDF components to values up to one
        # RGB level below the requested integer (15 -> 14). The tolerance is
        # explicit in this variant; the palette's 15-level gap is unchanged.
        y, x = np.where(np.all(np.abs(pixels - np.asarray(color, dtype=np.int16)) <= 1, axis=2))
        box = [int(x.min()) - 1, int(y.min()) - 1, int(x.max()) + 1, int(y.max()) + 1] if len(x) else []
        rows.append({"token": token, "bbox": box})
    image.convert("L").point(lambda pixel: 255 if pixel == 255 else 0, "1").convert("RGB").save(directory / "base.png")
    return rows, list(image.size)


def render_formula(raw, directory, runtime, *, content_format="LATEX", tex_cache=None):
    """Render into a NEW directory. Keep failures, raw source and all logs."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    _require(isinstance(raw, str), "Formula content must be a string")
    _require(content_format in ("LATEX", "TEXT", "MATHML"), "Unknown formula representation")
    method = runtime.get("method")
    engine = TEX_ENGINES.get(method)
    report = {"schema_version": SCHEMA, "method": method, "content_format": content_format, "tex_engine": engine,
              "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "status": "RENDER_FAILED",
              "reason": None, "error_kind": None, "processes": [], "tokens": [], "image_size": None,
              "source_characters": len(raw),
              "runtime_sha256": hashlib.sha256(_json_bytes(runtime)).hexdigest()}
    failure_kind = "EVALUATOR_ERROR"
    try:
        failure_kind = "EVALUATOR_LIMIT"
        _require(len(raw) <= MAX_CHARACTERS, "Formula source exceeds the character limit")
        (directory / "source.txt").write_text(raw, encoding="utf-8", newline="")
        failure_kind = "RUNTIME_IDENTITY_MISMATCH"
        _require(engine is not None, "Formula runtime method mismatch")
        for name in ("node", engine):
            tool = runtime["tools"][name]
            _require(_sha(tool["path"]) == tool["sha256"], f"Formula executable changed: {name}")
            for library in tool.get("adjacent_dlls", []):
                _require(_sha(Path(tool["path"]).parent / library["name"]) == library["sha256"],
                         f"Formula native library changed: {library['name']}")
        fonts = runtime["unicode_fonts"] if engine == "lualatex" else None
        if fonts is not None:
            _require(fonts.keys() == set(UNICODE_FONTS)
                     and all(_sha(row["path"]) == row["sha256"] for row in fonts.values()), "Unicode renderer font changed")
        failure_kind = "UNSUPPORTED_REPRESENTATION"
        _require(content_format == "LATEX", f"UNSUPPORTED_REPRESENTATION:{content_format}")
        failure_kind = "CONTENT_RENDER_FAILURE"
        _require(bool(raw.strip()), "Empty formula")
        failure_kind = "UNSUPPORTED_SOURCE"
        render_source = unicodedata.normalize("NFC", raw) if engine == "lualatex" else raw
        _require(not any(FORBIDDEN_COMMAND.search(value) or "^^" in value or "\x00" in value
                         for value in (raw, render_source)),
                 "Unsupported non-math TeX commands or control syntax")
        _require("tabular" not in raw and not re.search(r"\\(?:begin|end)\s*{document}", raw),
                 "Expected a mathematical expression, not a document or table")
        failure_kind = "EVALUATOR_ERROR"
        value, process = _tokenize(render_source, runtime["tools"]["node"]["path"], directory)
        report["processes"].append(process)
        _require(process["returncode"] == 0 and not process["timed_out"] and not process["output_limit_exceeded"],
                 "TOKENIZER_PROCESS_FAILED")
        if value is None:
            failure_kind = _tokenizer_error(directory, process)
            raise ValueError("TOKENIZATION_FAILED")
        failure_kind = "EVALUATOR_ERROR"
        tex, normalized, tokens, colors = _colored(value)
        if fonts is not None:
            tex = tex.replace(r"\begin{document}", UNICODE_SETUP + r"\begin{document}", 1)
        report.update(tokenized_latex=value, normalized_latex=normalized)
        (directory / "formula.tex").write_text(tex, encoding="utf-8", newline="\n")
        env = dict(os.environ)
        env.update(openin_any="p", openout_any="p", shell_escape="f", TEXMFOUTPUT=str(directory))
        if fonts is not None:
            cache = directory / "unicode-tex-cache" if tex_cache is None else tex_cache
            cache.mkdir(exist_ok=True)
            env.update(TEXMFCACHE=cache.as_posix(), TEXMFOUTPUT=cache.parent.as_posix(), max_print_line="4096",
                       OPENTYPEFONTS=os.pathsep.join(Path(row["path"]).parent.as_posix() for row in fonts.values()) + os.pathsep)
        format_arg = ["-fmt=lualatex"] if engine == "lualatex" else []
        process = _run([runtime["tools"][engine]["path"], *format_arg, "-no-shell-escape", "-halt-on-error",
                        "-interaction=nonstopmode", "-file-line-error", "-recorder", "formula.tex"],
                       directory, engine, env=env)
        report["processes"].append(process)
        _require(not process["timed_out"] and not process["output_limit_exceeded"], "TEX_PROCESS_LIMIT_EXCEEDED")
        if process["returncode"] != 0 or fonts is not None:
            console = (directory / process["stdout"]).read_text(encoding="utf-8", errors="replace")
            if fonts is not None and "Missing character:" in console:
                failure_kind = "MISSING_FONT_GLYPH"
                raise ValueError("UNICODE_FONT_GLYPH_MISSING")
        if process["returncode"] != 0:
            if re.search(r"LaTeX Error: File .+ not found|can't find the format file|I can't find file", console):
                failure_kind = "MISSING_TEX_DEPENDENCY"
            raise ValueError("TEX_COMPILATION_FAILED")
        report["tex_inputs"] = _tex_inputs(directory, fonts)
        rows, size = _glyphs(directory, tokens, colors)
        _write(directory / "glyphs.json", rows)
        report.update(tokens=rows, image_size=size, nonvisible_token_count=sum(not row["bbox"] for row in rows))
        _require(bool(rows), "NO_RENDERABLE_CHARACTERS")
        _require(all(row["bbox"] for row in rows), "UNLOCATED_COLORED_TOKENS")
        report.update(status="RENDERED")
    except (ValueError, OSError, IndexError, KeyError, RecursionError, subprocess.SubprocessError) as exc:
        if "exceeds the colored-token limit" in str(exc) or "exceeds the preprocessing limit" in str(exc):
            failure_kind = "EVALUATOR_LIMIT"
        report.update(reason=str(exc), error_kind=failure_kind)
    report["artifacts"] = [{"path": path.name, "sha256": _sha(path), "bytes": path.stat().st_size}
                           for path in sorted(directory.iterdir()) if path.is_file()]
    _write(directory / "render.json", report)
    return report


def _validated_glyphs(render, method):
    _require(render.get("method") == method, "Rendered formula method mismatch")
    size = render.get("image_size")
    _require(isinstance(size, list) and len(size) == 2 and all(type(value) is int and value > 0 for value in size),
             "Rendered formula requires positive integer image dimensions")
    tokens = render.get("tokens")
    _require(isinstance(tokens, list) and 0 < len(tokens) <= MAX_TOKENS, "Invalid rendered formula glyph count")
    for row in tokens:
        box = row.get("bbox") if isinstance(row, dict) else None
        _require(isinstance(box, list) and len(box) == 4
                 and all(type(value) in (int, float) and math.isfinite(value) for value in box)
                 and 0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]
                 and isinstance(row.get("token"), str) and bool(row["token"]),
                 "Rendered glyph requires a nonempty token and finite positive-area in-image bbox")
    return tokens


def compare_renders(reference, prediction):
    """Return unrounded counts; never drop a failed reference from its cohort."""
    method = reference.get("method", METHOD)
    _require(method in (METHOD, LEGACY_METHOD), "Rendered formula method mismatch")
    result = {"method": method, "status": "NOT_EVALUATED", "reason": None, "tp": None, "fp": None,
              "fn": None, "reference_characters": None, "prediction_characters": None,
              "precision": None, "recall": None, "cdm_f1": None, "rendered_character_exact": None,
              "normalized_latex_equal": None, "review_reasons": [], "matches": []}
    if reference.get("status") != "RENDERED":
        return {**result, "reason": "REFERENCE_RENDER_FAILED"}
    gt = _validated_glyphs(reference, method)
    result.update(reference_characters=len(gt))
    if prediction is None or prediction.get("status") != "RENDERED":
        if prediction is not None and prediction.get("error_kind") != "CONTENT_RENDER_FAILURE":
            return {**result, "reason": "PREDICTION_EVALUATOR_UNSUPPORTED_OR_FAILED",
                    "prediction_error_kind": prediction.get("error_kind")}
        return {**result, "status": "MEASURED", "reason": "MISSING_PREDICTION" if prediction is None else "PREDICTION_RENDER_FAILED",
                "tp": 0, "fn": len(gt), "fp": 0 if prediction is None else None,
                "prediction_characters": 0 if prediction is None else None, "recall": 0., "cdm_f1": 0.,
                "rendered_character_exact": False}
    import numpy as np
    from skimage.measure import ransac
    from ._vendor.unimernet_cdm.visual_matcher import HungarianMatcher, SimpleAffineTransform

    class ExplicitSuccessTransform(SimpleAffineTransform):
        # skimage 0.26 requires an explicit success result; the reference
        # implementation returns None. The fitted transform is unchanged.
        def estimate(self, source, destination):
            super().estimate(source, destination)
            return bool(np.isfinite(self.scale) and np.all(np.isfinite(self.translation)))

        @classmethod
        def from_estimate(cls, source, destination):
            model = cls()
            return model if model.estimate(source, destination) else None

    pred = _validated_glyphs(prediction, method)
    _require(reference.get("tex_engine") == prediction.get("tex_engine") or method == LEGACY_METHOD,
             "Formula pair must use the same TeX engine on both sides")
    if method == METHOD:
        gt, pred = ([{**row, "token": UNICODE_MATH_ALIASES.get(row["token"], row["token"])} for row in rows]
                    for rows in (gt, pred))
    matcher = HungarianMatcher()
    matched = matcher(gt, pred, reference["image_size"], prediction["image_size"])
    src, dst = [np.asarray([[(rows[index]["bbox"][1] + rows[index]["bbox"][3]) / 2,
                           (rows[index]["bbox"][0] + rows[index]["bbox"][2]) / 2]
                          for index in indexes]) for rows, indexes in
                ((gt, [a for a, _ in matched]), (pred, [b for _, b in matched]))]
    inliers = np.ones(len(matched), dtype=bool) if len(matched) <= 2 else np.zeros(len(matched), dtype=bool)
    seed = {"rng": 42} if "rng" in inspect.signature(ransac).parameters else {"random_state": 42}
    for _ in range(5):
        remaining = ~inliers
        if remaining.sum() <= 2:
            break
        _, found = ransac((src[remaining], dst[remaining]), ExplicitSuccessTransform, min_samples=2,
                          residual_threshold=20, max_trials=50, **seed)
        if found is None or not found.any():
            break
        inliers[np.flatnonzero(remaining)[found]] = True
    for index, (a, b) in enumerate(matched):
        if matcher.cost["token"][a, b] == 1:
            inliers[index] = False
    tp = int(inliers.sum())
    matches = [{"reference_index": int(a), "prediction_index": int(b), "accepted": bool(accepted),
                "token_cost": float(matcher.cost["token"][a, b])}
               for (a, b), accepted in zip(matched, inliers)]
    normalized_equal = (reference["normalized_latex"] == prediction["normalized_latex"]
                        if all(isinstance(row.get("normalized_latex"), str) for row in (reference, prediction)) else None)
    review = ["CHARACTER_MATCH_DOES_NOT_VALIDATE_CRITICAL_STRUCTURE"] if normalized_equal is False else []
    return {**result, "status": "MEASURED", "tp": tp, "fp": len(pred) - tp, "fn": len(gt) - tp,
            "prediction_characters": len(pred), "precision": tp / len(pred), "recall": tp / len(gt),
            "cdm_f1": 2 * tp / (len(gt) + len(pred)), "rendered_character_exact": tp == len(gt) == len(pred),
            "normalized_latex_equal": normalized_equal, "review_reasons": review, "matches": matches}


def evaluate_pairs(pairs, output, *, node, pdflatex=None, lualatex=None, expected_runtime=None):
    """Execute an explicit controlled/development pair set, without GT claims."""
    _require(isinstance(pairs, list) and pairs, "Formula comparison requires an explicit nonempty pair list")
    ids = [row.get("id") for row in pairs if isinstance(row, dict)]
    _require(len(ids) == len(pairs) and all(isinstance(key, str) and key.strip() for key in ids)
             and len(set(ids)) == len(ids), "Formula pairs require unique nonempty IDs")
    for pair in pairs:
        _require(isinstance(pair.get("reference"), str) and
                 (pair.get("prediction") is None or isinstance(pair["prediction"], str)) and
                 all(pair.get(f"{side}_format", "LATEX") in ("LATEX", "TEXT", "MATHML")
                     for side in ("reference", "prediction")), "Invalid formula pair content or format")
    output = Path(output).resolve()
    _require(not any((parent / marker).is_file() for parent in (output, *output.parents)
                     for marker in ("batch_input_manifest.json", "COMPLETED.json")),
             "Formula evaluation output must stay outside canonical publications")
    output.mkdir(parents=True, exist_ok=False)
    runtime = runtime_identity(node, pdflatex, output, lualatex)
    method = runtime["method"]
    _write(output / "runtime.json", runtime)
    if expected_runtime is not None:
        _require(runtime_signature(runtime) == runtime_signature(expected_runtime),
                 "Observed formula runtime differs from the locked renderer")
    rows = []
    for index, pair in enumerate(pairs):
        key = f"{index:05d}-" + hashlib.sha256(pair["id"].encode("utf-8")).hexdigest()[:16]
        reference = render_formula(pair["reference"], output / key / "reference", runtime,
                                   content_format=pair.get("reference_format", "LATEX"), tex_cache=output / "unicode-tex-cache")
        prediction = None if pair.get("prediction") is None else render_formula(
            pair["prediction"], output / key / "prediction", runtime,
            content_format=pair.get("prediction_format", "LATEX"), tex_cache=output / "unicode-tex-cache")
        comparison = compare_renders(reference, prediction)
        rows.append({"id": pair["id"], "directory": key, "reference_status": reference["status"],
                     "reference_error_kind": reference.get("error_kind"),
                     "prediction_status": None if prediction is None else prediction["status"],
                     "prediction_error_kind": None if prediction is None else prediction.get("error_kind"), **comparison})
    measured = [row for row in rows if row["status"] == "MEASURED"]
    complete = len(measured) == len(rows)
    report = {"schema_version": SCHEMA, "method": method, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "MEASURED" if complete else "NOT_EVALUATED", "pairs": len(rows),
              "measured_pairs": len(measured), "unscorable_pairs": len(rows) - len(measured),
              "reference_render_failures": sum(row["reference_status"] != "RENDERED" for row in rows),
              "mean_cdm": sum(row["cdm_f1"] for row in measured) / len(rows) if complete else None,
              "rendered_character_exact_rate": sum(row["rendered_character_exact"] for row in measured) / len(rows) if complete else None,
              "diagnostic_measured_subset_mean": sum(row["cdm_f1"] for row in measured) / len(measured) if measured else None,
              "acceptance_status": "NOT_EVALUATED", "independent_ground_truth_verified": False,
              "limitation": "Pair comparison only. No source-position matching, spurious-formula penalty, human provenance validation or release thresholds.",
              "runtime_sha256": _sha(output / "runtime.json"), "details": rows}
    _write(output / "comparison.json", report)
    return report


def evaluate_pair_file(pairs_path, output, *, node, pdflatex=None, lualatex=None,
                       expected_runtime_path=None, expected_runtime_sha256=None):
    pairs, pairs_hash = _read_json(pairs_path)
    expected = None
    _require((expected_runtime_path is None) == (expected_runtime_sha256 is None),
             "Expected formula runtime path and SHA-256 must be supplied together")
    if expected_runtime_path is not None:
        expected, digest = _read_json(expected_runtime_path)
        _require(digest == expected_runtime_sha256, "Locked formula runtime SHA-256 differs")
    report = evaluate_pairs(pairs, output, node=node, pdflatex=pdflatex, lualatex=lualatex, expected_runtime=expected)
    _require(_sha(pairs_path) == pairs_hash, "Formula pair file changed during rendering")
    if expected is not None:
        _require(_sha(expected_runtime_path) == expected_runtime_sha256, "Locked formula runtime changed during rendering")
    _write(output / "input.json", {"path": str(pairs_path.resolve()), "sha256": pairs_hash,
           "expected_runtime_sha256": expected_runtime_sha256})
    return report


def _verified_render(directory, raw, content_format, runtime, runtime_hash):
    report, _ = _read_json(directory / "render.json")
    method = runtime["method"]
    _require(report.get("schema_version") == SCHEMA and report.get("status") in ("RENDERED", "RENDER_FAILED")
             and report.get("method") == method and report.get("raw_sha256") == hashlib.sha256(raw.encode("utf-8")).hexdigest()
             and report.get("content_format") == content_format and report.get("runtime_sha256") == runtime_hash,
             "Rendered formula source, format or runtime differs")
    _require(method == LEGACY_METHOD or report.get("tex_engine") == TEX_ENGINES[method], "Rendered formula engine differs from method")
    artifacts = report["artifacts"]
    names = [row["path"] for row in artifacts]
    _require(len(set(names)) == len(names) and all(isinstance(name, str) and Path(name).name == name
             and name not in (".", "..", "render.json") and not Path(name).anchor for name in names),
             "Invalid or duplicate formula render artifact")
    for row in artifacts:
        path = (directory / row["path"]).resolve()
        _require(path.parent == directory.resolve() and _sha(path) == row["sha256"] and path.stat().st_size == row["bytes"],
                 "Formula render artifact changed")
    if len(raw) <= MAX_CHARACTERS:
        _require("source.txt" in names and (directory / "source.txt").read_bytes() == raw.encode("utf-8"),
                 "Rendered formula raw bytes differ")
    if report["status"] == "RENDERED":
        _require(content_format == "LATEX" and {"glyphs.json", "colored.png", "base.png", "formula.pdf", "formula.tex"} <= set(names),
                 "Rendered formula lacks glyph, image or TeX evidence")
        glyphs, _ = _read_json(directory / "glyphs.json")
        _require(glyphs == report["tokens"], "Rendered glyph report differs from its token artifact")
        tex_inputs = report.get("tex_inputs")
        _require(isinstance(tex_inputs, list) and tex_inputs and all(_sha(item["path"]) == item["sha256"] for item in tex_inputs),
                 "Used TeX input evidence is missing or changed")
        if method == METHOD:
            _require({"formula.log", "formula.fls"} <= set(names)
                     and tex_inputs == _tex_inputs(directory, runtime["unicode_fonts"]), "Unicode TeX inputs differ from render evidence")
    return report


def verify_comparison(directory, pairs_path, *, expected_runtime_path=None, expected_runtime_sha256=None):
    """Recompute character matching from source-bound, hash-checked render evidence."""
    directory = Path(directory).resolve()
    pairs, pairs_hash = _read_json(pairs_path)
    report, digest = _read_json(directory / "comparison.json")
    source, input_hash = _read_json(directory / "input.json")
    runtime, runtime_hash = _read_json(directory / "runtime.json")
    _require((expected_runtime_path is None) == (expected_runtime_sha256 is None),
             "Expected formula runtime path and SHA-256 must be supplied together")
    method = runtime.get("method")
    _require(source.get("sha256") == pairs_hash and report.get("schema_version") == SCHEMA
             and method in (METHOD, LEGACY_METHOD) and report.get("method") == method and report.get("runtime_sha256") == runtime_hash,
             "CDM input, method or runtime identity differs")
    if expected_runtime_path is not None:
        expected, expected_hash = _read_json(expected_runtime_path)
        _require(expected_hash == expected_runtime_sha256 == source.get("expected_runtime_sha256")
                 and runtime_signature(runtime) == runtime_signature(expected), "CDM runtime differs from the locked renderer")
    rows = report["details"]
    _require(isinstance(pairs, list) and len(rows) == report["pairs"] == len(pairs)
             and len({pair["id"] for pair in pairs}) == len(pairs), "CDM report must cover every source pair")
    scores = {}
    for index, (pair, row) in enumerate(zip(pairs, rows, strict=True)):
        name = f"{index:05d}-" + hashlib.sha256(pair["id"].encode("utf-8")).hexdigest()[:16]
        _require(row.get("id") == pair["id"] and row.get("directory") == name, "CDM pair order or directory differs")
        reference = _verified_render(directory / name / "reference", pair["reference"],
                                     pair.get("reference_format", "LATEX"), runtime, runtime_hash)
        prediction = None if pair.get("prediction") is None else _verified_render(directory / name / "prediction",
            pair["prediction"], pair.get("prediction_format", "LATEX"), runtime, runtime_hash)
        recomputed = compare_renders(reference, prediction)
        _require(all(row.get(key) == value for key, value in recomputed.items()),
                 "CDM comparison differs from recomputed render matching")
        if recomputed["status"] == "MEASURED":
            scores[pair["id"]] = recomputed["cdm_f1"]
    _require(_sha(directory / "comparison.json") == digest and _sha(directory / "runtime.json") == runtime_hash
             and _sha(directory / "input.json") == input_hash and _sha(pairs_path) == pairs_hash,
             "CDM evidence changed during recomputation")
    return scores, {"comparison_sha256": digest, "input_sha256": input_hash, "runtime_sha256": runtime_hash,
                    "render_evidence_verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    tex = parser.add_mutually_exclusive_group(required=True)
    tex.add_argument("--pdflatex", type=Path, help="Legacy diagnostic method")
    tex.add_argument("--lualatex", type=Path, help="Unicode CDM method required for v7.0 holdout")
    parser.add_argument("--expected-runtime", type=Path)
    parser.add_argument("--expected-runtime-sha256")
    args = parser.parse_args(argv)
    try:
        report = evaluate_pair_file(args.pairs, args.output, node=args.node, pdflatex=args.pdflatex, lualatex=args.lualatex,
            expected_runtime_path=args.expected_runtime, expected_runtime_sha256=args.expected_runtime_sha256)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in ("status", "pairs", "measured_pairs", "mean_cdm", "acceptance_status")}))
    return 0 if report["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
