from __future__ import annotations

import base64
import bz2
import gzip
import lzma
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS_DIR = ROOT / "no-promises-v28-3-beta"
OUTPUT = ROOT / "no-promises-v28-mobile.html"
STATIC_DIR = ROOT / "no-promises-v28-3-static"
EXPECTED_PARTS = 21


def valid_html(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    lower = text.lower()
    return "<!doctype html" in lower and "v28.3" in lower and "beta test" in lower


def try_decode(data: bytes, label: str, diagnostics: list[str]) -> bytes | None:
    candidates = [
        ("plain", lambda b: b),
        ("gzip", gzip.decompress),
        ("zlib", zlib.decompress),
        ("raw-deflate", lambda b: zlib.decompress(b, -zlib.MAX_WBITS)),
        ("bz2", bz2.decompress),
        ("lzma", lzma.decompress),
    ]
    for method, fn in candidates:
        try:
            out = fn(data)
        except Exception as exc:
            diagnostics.append(f"{label}/{method}: {type(exc).__name__}: {exc}")
            continue
        if valid_html(out):
            print(f"Recovered valid HTML with {label}/{method}: {len(out):,} bytes")
            return out
        diagnostics.append(f"{label}/{method}: produced {len(out):,} bytes, prefix={out[:12].hex()}")
    return None


def split_static(html: str) -> None:
    STATIC_DIR.mkdir(exist_ok=True)
    style = re.search(r"<style>(.*?)</style>", html, re.S)
    script = re.search(r"<script>(.*?)</script>", html, re.S)
    if not style or not script:
        raise RuntimeError("Recovered HTML does not contain the expected inline style/script blocks")

    css = style.group(1)
    js = script.group(1)
    shell = re.sub(r"<style>.*?</style>", '<link rel="stylesheet" href="styles.css">', html, flags=re.S)
    shell = re.sub(r"<script>.*?</script>", '<script src="app.js"></script>', shell, flags=re.S)
    shell = shell.replace("Mobile Plus V28.2", "V28.3 Static Beta")

    (STATIC_DIR / "index.html").write_text(shell, encoding="utf-8")
    (STATIC_DIR / "styles.css").write_text(css, encoding="utf-8")
    (STATIC_DIR / "app.js").write_text(js, encoding="utf-8")


def main() -> int:
    part_paths = [PARTS_DIR / f"part-{i:02d}.txt" for i in range(EXPECTED_PARTS)]
    missing = [str(p) for p in part_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing payload parts: {missing}")

    encoded = [p.read_text(encoding="utf-8").strip() for p in part_paths]
    decoded = []
    for i, value in enumerate(encoded):
        try:
            decoded.append(base64.b64decode(value, validate=True))
        except Exception as exc:
            raise RuntimeError(f"Part {i:02d} is not valid Base64: {exc}") from exc

    print("Encoded sizes:", [len(x) for x in encoded])
    print("Decoded sizes:", [len(x) for x in decoded])
    print("First decoded bytes:", decoded[0][:24].hex())

    diagnostics = []
    combined = b"".join(decoded)
    recovered = try_decode(combined, "decoded-parts-concatenated", diagnostics)

    if recovered is None:
        for method_name, fn in [
            ("gzip", gzip.decompress),
            ("zlib", zlib.decompress),
            ("raw-deflate", lambda b: zlib.decompress(b, -zlib.MAX_WBITS)),
            ("bz2", bz2.decompress),
            ("lzma", lzma.decompress),
            ("plain", lambda b: b),
        ]:
            outputs = []
            try:
                for part in decoded:
                    outputs.append(fn(part))
            except Exception as exc:
                diagnostics.append(f"per-part/{method_name}: {type(exc).__name__}: {exc}")
                continue
            candidate = b"".join(outputs)
            if valid_html(candidate):
                recovered = candidate
                print(f"Recovered valid HTML with per-part/{method_name}: {len(candidate):,} bytes")
                break
            diagnostics.append(f"per-part/{method_name}: produced {len(candidate):,} bytes, prefix={candidate[:12].hex()}")

    if recovered is None:
        joined = "".join(x.rstrip("=") for x in encoded)
        joined += "=" * ((4 - len(joined) % 4) % 4)
        try:
            joined_bytes = base64.b64decode(joined, validate=True)
        except Exception as exc:
            diagnostics.append(f"joined-base64: {type(exc).__name__}: {exc}")
        else:
            recovered = try_decode(joined_bytes, "joined-base64", diagnostics)

    if recovered is None:
        print("\nRecovery diagnostics:")
        for line in diagnostics:
            print(" -", line)
        raise RuntimeError("Could not reconstruct a valid V28.3 HTML file from the deployed payload")

    OUTPUT.write_bytes(recovered)
    split_static(recovered.decode("utf-8"))
    print(f"Wrote plain HTML: {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
    print(f"Wrote static site: {STATIC_DIR}")
    return 0


if __name__ == "__main__":
    # Deployment retrigger: 2026-08-06 static build publish.
    sys.exit(main())
