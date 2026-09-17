"""
AI Horde Client — Decentralized, Uncensored Free AI Image Generation
=====================================================================
Uses AI Horde (https://aihorde.net) to provide 100% uncensored (NSFW-allowed)
image generations powered by volunteer GPUs.
"""

import base64
import json
import logging
import random
import socket
import time
import requests
import urllib3.util.connection as urllib3_cn

# Force IPv4 resolution to prevent 'Network is unreachable' on cloud VMs without IPv6 egress
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

logger = logging.getLogger("aihorde_client")

HORDE_ENDPOINT = "https://aihorde.net/api/v2"
ANONYMOUS_KEY = "0000000000"
CLIENT_AGENT = "azimagegenbot:1.0"

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
    negative_prompt: str = "blurry, low quality, deformed, bad anatomy, watermark",
    width: int = 512,
    height: int = 512,
    seed: int = None,
    api_key: str = ANONYMOUS_KEY,
    timeout: int = 90
) -> bytes:
    """
    Submits a generation request to AI Horde with NSFW enabled and returns the image bytes.
    Uses requests Session with clean browser headers and IPv4 enforcement.
    """
    w = (min(max(width, 384), 1024) // 64) * 64
    h = (min(max(height, 384), 1024) // 64) * 64

    if seed is None:
        seed = random.randint(0, 2**31 - 1)

    full_prompt = f"{prompt} ### {negative_prompt}" if negative_prompt else prompt

    session = requests.Session()
    session.headers.update({
        "Client-Agent": CLIENT_AGENT,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "apikey": api_key if (api_key and api_key.strip()) else ANONYMOUS_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    })

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

    job_id = None
    last_err = None
    for attempt in range(1, 4):
        try:
            res = session.post(f"{HORDE_ENDPOINT}/generate/async", json=payload, timeout=20)
            if res.status_code == 202:
                res_data = res.json()
                job_id = res_data.get("id")
                if job_id:
                    logger.info(f"AI Horde job submitted successfully: {job_id}")
                    break
            last_err = f"Status {res.status_code}: {res.text[:150]}"
        except Exception as e:
            last_err = str(e)
            logger.warning(f"AI Horde submit attempt {attempt} failed: {e}")
        time.sleep(3)

    if not job_id:
        raise RuntimeError(f"Failed to submit job to AI Horde after retries: {last_err}")

    # Poll for completion
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(3)
        try:
            check_res = session.get(f"{HORDE_ENDPOINT}/generate/check/{job_id}", timeout=15)
            if check_res.status_code == 200:
                check_data = check_res.json()
                if check_data.get("faulted"):
                    raise RuntimeError("AI Horde worker faulted while processing generation.")

                if check_data.get("done"):
                    status_res = session.get(f"{HORDE_ENDPOINT}/generate/status/{job_id}", timeout=15)
                    if status_res.status_code == 200:
                        status_data = status_res.json()
                        gens = status_data.get("generations", [])
                        if not gens:
                            raise RuntimeError("No generation data returned from AI Horde.")
                        
                        img_url_or_data = gens[0].get("img", "")
                        if img_url_or_data.startswith("http://") or img_url_or_data.startswith("https://"):
                            img_download = session.get(img_url_or_data, timeout=30)
                            return img_download.content
                        elif img_url_or_data.startswith("data:image"):
                            _, b64data = img_url_or_data.split(",", 1)
                            return base64.b64decode(b64data)
                        else:
                            return base64.b64decode(img_url_or_data)
        except Exception as e:
            logger.warning(f"Waiting for AI Horde job {job_id}: {e}")

    raise TimeoutError(f"AI Horde generation timed out after {timeout}s in queue.")
