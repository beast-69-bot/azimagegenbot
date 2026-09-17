"""
Pollinations.ai — Free Unlimited AI Image Generator Client
============================================================

This is the TRULY FREE, NO-AUTH, NO-KEY way to generate AI images
from a Python script.
"""

import argparse
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENDPOINT = "https://image.pollinations.ai/prompt"
DEFAULT_MODEL   = "flux"     # available: flux, turbo, sana (default)
DEFAULT_WIDTH  = 1024
DEFAULT_HEIGHT = 1024
TIMEOUT_SEC    = 120        # high because cold generations can take 30-60s
MAX_RETRIES    = 3
RETRY_BACKOFF  = 8          # seconds to wait when queue full


# ---------------------------------------------------------------------------
# Core: generate one image. Returns the bytes (JPEG) on success.
# ---------------------------------------------------------------------------
def generate_image(prompt: str,
                    model: str = DEFAULT_MODEL,
                    width: int  = DEFAULT_WIDTH,
                    height: int = DEFAULT_HEIGHT,
                    seed: int   = None,
                    nologo: bool = True,
                    timeout: int = TIMEOUT_SEC) -> bytes:
    """
    Hit the Pollinations endpoint and return JPEG bytes.

    Raises:
        RuntimeError — if all retries fail (queue full, 5xx, etc.)
    """
    if seed is None:
        seed = random.randint(0, 2**31 - 1)

    params = {
        "model":  model,
        "width":  str(width),
        "height": str(height),
        "seed":   str(seed),
        "nologo": "true" if nologo else "false",
    }
    url = ENDPOINT + "/" + urllib.parse.quote(prompt, safe="")
    url += "?" + urllib.parse.urlencode(params)

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept":     "image/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ct = r.headers.get("Content-Type", "")
                body = r.read()
                if "image" in ct and len(body) > 1000:
                    return body
                # else likely a JSON error from the queue
                last_err = f"[attempt {attempt}] non-image response " \
                           f"(type={ct}, len={len(body)}): " \
                           f"{body[:300].decode('utf-8', 'replace')}"
                print(last_err, file=sys.stderr)
                # short retry — likely "Queue full for IP"
                time.sleep(RETRY_BACKOFF)
                continue
        except Exception as e:
            last_err = f"[attempt {attempt}] request error: {e}"
            print(last_err, file=sys.stderr)
            time.sleep(RETRY_BACKOFF)

    raise RuntimeError(f"all {MAX_RETRIES} attempts failed. Last: {last_err}")


# ---------------------------------------------------------------------------
# Batch generator with polite pacing
# ---------------------------------------------------------------------------
def batch_generate(prompt: str, count: int, out_dir: Path, prefix: str = "img",
                    model: str = DEFAULT_MODEL, width: int = DEFAULT_WIDTH,
                    height: int = DEFAULT_HEIGHT, seed: int = None,
                    delay: float = 2.0):
    """
    Generate `count` images serially (per Pollinations' 1-IP queue limit),
    saving each as <out_dir>/<prefix>_<i:03d>_seed<S>.jpg
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    successes = 0
    for i in range(count):
        s = seed if seed is not None else random.randint(0, 2**31 - 1)
        try:
            data = generate_image(prompt, model=model, width=width, height=height, seed=s)
            fname = out_dir / f"{prefix}_{i:03d}_seed{s}.jpg"
            fname.write_bytes(data)
            print(f"[{i+1}/{count}] OK  {len(data)//1024} KB -> {fname}")
            successes += 1
        except Exception as e:
            print(f"[{i+1}/{count}] FAIL: {e}", file=sys.stderr)
        if i < count - 1:
            time.sleep(delay)
    print(f"\nDone. {successes}/{count} images saved to {out_dir}/")
    return successes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Pollinations.ai — free unlimited AI image generator")
    ap.add_argument("-p", "--prompt", required=True,
                    help="Prompt text (any language)")
    ap.add_argument("-N", "--count", type=int, default=1,
                    help="How many images to generate (default 1)")
    ap.add_argument("-o", "--out", default="download/pollinations_images",
                    help="Output directory")
    ap.add_argument("--prefix", default="img",
                    help="Filename prefix (default 'img')")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    choices=["flux", "turbo", "sana"],
                    help="Which model to use (default: flux)")
    ap.add_argument("--width",  type=int, default=DEFAULT_WIDTH,
                    help="Image width in pixels (default 1024)")
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT,
                    help="Image height in pixels (default 1024)")
    ap.add_argument("--seed", type=int, default=None,
                    help="Reproducible seed (default: random per image)")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="Seconds between requests (default 2)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    batch_generate(
        prompt   = args.prompt,
        count    = args.count,
        out_dir  = out_dir,
        prefix   = args.prefix,
        model    = args.model,
        width    = args.width,
        height   = args.height,
        seed     = args.seed,
        delay    = args.delay,
    )


if __name__ == "__main__":
    main()
