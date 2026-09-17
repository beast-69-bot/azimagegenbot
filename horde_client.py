"""
AI Horde Client — Decentralized, Uncensored Free AI Image Generation
=====================================================================
Uses AI Horde (https://aihorde.net) to provide 100% uncensored (NSFW-allowed)
image generations powered by volunteer GPUs.
"""

import io
import json
import logging
import random
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("aihorde_client")

HORDE_ENDPOINT = "https://aihorde.net/api/v2"
ANONYMOUS_KEY = "0000000000"
CLIENT_AGENT = "azimagegenbot:1.0:azblackbox123@gmail.com"

# Popular uncensored / artistic models on AI Horde
POPULAR_UNCENSORED_MODELS = [
    "AbsoluteReality",
    "ICBINP - I Can't Believe It's Not Photography",
    "Deliberate",
    "AbyssOrangeMix",
    "stable_diffusion"
]

def generate_horde_image(
    prompt: str,
    negative_prompt: str = "blurry, low quality, deformed, bad anatomy",
    width: int = 512,
    height: int = 512,
    seed: int = None,
    api_key: str = ANONYMOUS_KEY,
    timeout: int = 90
) -> bytes:
    """
    Submits a generation request to AI Horde with NSFW enabled and returns the image bytes.
    """
    # AI Horde standard SD 1.5/SDXL resolutions should ideally be multiples of 64
    w = (min(max(width, 384), 1024) // 64) * 64
    h = (min(max(height, 384), 1024) // 64) * 64

    if seed is None:
        seed = random.randint(0, 2**31 - 1)

    full_prompt = f"{prompt} ### {negative_prompt}" if negative_prompt else prompt

    headers = {
        "Client-Agent": CLIENT_AGENT,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "apikey": api_key or ANONYMOUS_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "prompt": full_prompt,
        "params": {
            "width": w,
            "height": h,
            "steps": 25,
            "seed": str(seed),
            "sampler_name": "k_euler",
            "cfg_scale": 7.0,
            "nsfw": True,
            "censor_nsfw": False
        },
        "nsfw": True,
        "censor_nsfw": False,
        "models": POPULAR_UNCENSORED_MODELS
    }

    # 1. Submit asynchronous job
    post_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{HORDE_ENDPOINT}/generate/async",
        data=post_data,
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            job_id = res_data.get("id")
            if not job_id:
                raise RuntimeError(f"AI Horde did not return a job ID: {res_data}")
            logger.info(f"AI Horde job submitted: {job_id}")
    except Exception as e:
        raise RuntimeError(f"Failed to submit job to AI Horde: {e}")

    # 2. Poll for completion
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(3)
        check_req = urllib.request.Request(
            f"{HORDE_ENDPOINT}/generate/check/{job_id}",
            headers=headers
        )
        try:
            with urllib.request.urlopen(check_req, timeout=15) as c_res:
                check_data = json.loads(c_res.read().decode("utf-8"))
                if check_data.get("faulted"):
                    raise RuntimeError("AI Horde worker faulted while processing generation.")

                if check_data.get("done"):
                    # 3. Retrieve final status
                    status_req = urllib.request.Request(
                        f"{HORDE_ENDPOINT}/generate/status/{job_id}",
                        headers=headers
                    )
                    with urllib.request.urlopen(status_req, timeout=15) as s_res:
                        status_data = json.loads(s_res.read().decode("utf-8"))
                        gens = status_data.get("generations", [])
                        if not gens:
                            raise RuntimeError("No generation data returned from AI Horde.")
                        img_url_or_data = gens[0].get("img")

                        # If it's a URL, download it
                        if img_url_or_data.startswith("http://") or img_url_or_data.startswith("https://"):
                            img_req = urllib.request.Request(img_url_or_data, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(img_req, timeout=30) as ir:
                                return ir.read()
                        elif img_url_or_data.startswith("data:image"):
                            import base64
                            header, b64data = img_url_or_data.split(",", 1)
                            return base64.b64decode(b64data)
                        else:
                            import base64
                            return base64.b64decode(img_url_or_data)
        except Exception as e:
            logger.warning(f"Error checking AI Horde job {job_id}: {e}")

    raise TimeoutError(f"AI Horde generation timed out after {timeout}s in queue.")
