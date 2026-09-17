"""
Face Swap Engine — High-Fidelity Neural Face Swapping & Identity-Preserved Generation
=====================================================================================
Powered by InsightFace (ArcFace 512-d embeddings) and INSwapper (inswapper_128.onnx).
Supports:
1. Photo-to-Photo Face Swapping (Source Face onto Target Photo).
2. Face + Prompt Generation (Generates scene from prompt and maps Face onto character).
"""

import os
import io
import time
import logging
import cv2
import numpy as np
from pathlib import Path
import insightface
from insightface.app import FaceAnalysis

import config
import pollinations_client
import horde_client

logger = logging.getLogger("faceswap_engine")

# Lazy-loaded singletons
_app = None
_swapper = None

def get_face_analyzer() -> FaceAnalysis:
    global _app
    if _app is None:
        logger.info("Initializing buffalo_l FaceAnalysis...")
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.3)
    return _app

def get_swapper():
    global _swapper
    if _swapper is None:
        model_path = config.BASE_DIR / "models" / "inswapper_128.onnx"
        if not model_path.exists():
            raise FileNotFoundError(f"Inswapper model not found at {model_path}")
        logger.info(f"Loading Inswapper model from {model_path}...")
        _swapper = insightface.model_zoo.get_model(str(model_path), download=False, check_hash=False)
    return _swapper


def detect_faces_with_fallback(app: FaceAnalysis, img: np.ndarray):
    """
    Detects faces in an image with progressive sensitivity fallback:
    1. Standard threshold (0.3)
    2. Sensitive threshold (0.15)
    3. Ultra-sensitive threshold (0.08)
    """
    faces = app.get(img)
    if faces:
        return faces

    # Fallback to lower detection thresholds for stylized or angled faces
    det_model = app.models.get('detection')
    orig_thresh = getattr(det_model, 'det_thresh', 0.3) if det_model else 0.3

    for fallback_thresh in [0.15, 0.08]:
        try:
            if det_model:
                det_model.det_thresh = fallback_thresh
            faces = app.get(img)
            if faces:
                logger.info(f"Face detected with fallback threshold: {fallback_thresh}")
                return faces
        finally:
            if det_model:
                det_model.det_thresh = orig_thresh

    return []


def swap_face(source_bytes: bytes, target_bytes: bytes) -> bytes:
    """
    Swaps face from source image onto target image.
    Returns JPEG bytes of the resulting image.
    """
    app = get_face_analyzer()
    swapper = get_swapper()

    # Decode images into OpenCV BGR arrays
    source_img = cv2.imdecode(np.frombuffer(source_bytes, np.uint8), cv2.IMREAD_COLOR)
    target_img = cv2.imdecode(np.frombuffer(target_bytes, np.uint8), cv2.IMREAD_COLOR)

    if source_img is None:
        raise ValueError("Source image invalid ya corrupt hai.")
    if target_img is None:
        raise ValueError("Target image invalid ya corrupt hai.")

    # Detect faces in source
    source_faces = detect_faces_with_fallback(app, source_img)
    if not source_faces:
        raise ValueError("Source photo me koi saaf chehra detect nahi hua! Kripya kisi aisi photo bhejein jisme chehra saaf dikh raha ho.")

    # Select largest face in source
    source_face = sorted(
        source_faces,
        key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]),
        reverse=True
    )[0]

    # Detect faces in target
    target_faces = detect_faces_with_fallback(app, target_img)
    if not target_faces:
        raise ValueError("Target photo me koi chehra detect nahi hua! Kripya target photo me aisi picture bhejein jisme insaan ka chehra visible ho.")

    # Select largest face in target
    target_face = sorted(
        target_faces,
        key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]),
        reverse=True
    )[0]

    # Perform swap
    result_img = swapper.get(target_img, target_face, source_face, paste_back=True)

    # Encode back to JPEG
    success, encoded = cv2.imencode(".jpg", result_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success:
        raise RuntimeError("Resulting image ko encode karne me error aaya.")

    return encoded.tobytes()


def clean_and_enhance_prompt(prompt: str, is_female: bool) -> str:
    """
    Normalizes conversational commands like 'put dress on her body' into descriptive
    portrait prompts that ensure the AI generates a clear human face and body.
    """
    import re
    p = prompt.strip()

    # Normalize command phrases like 'put dress on her body', 'wear saree', etc.
    replacements = [
        (r"^(put|give|add|wear)\s+(a\s+|an\s+)?", "wearing a "),
        (r"\s+on\s+(her|his|my|the)\s+body", ""),
        (r"\s+on\s+(her|him|me)", ""),
        (r"^make\s+(her|him)\s+", ""),
        (r"^change\s+(her|his)\s+clothes\s+to\s+", "wearing "),
    ]
    for pattern, repl in replacements:
        p = re.sub(pattern, repl, p, flags=re.IGNORECASE).strip()

    subject = "beautiful woman" if is_female else "handsome man"

    # Check if a human subject is already mentioned
    has_person = any(w in p.lower() for w in ["woman", "girl", "lady", "female", "man", "guy", "boy", "male", "person", "character", "king", "queen", "prince", "princess", "warrior", "model", "superhero"])

    if has_person:
        enhanced = f"portrait photo of {p}, clear detailed visible human face looking directly at camera, sharp focus, 8k resolution, cinematic lighting"
    else:
        # e.g. "wearing a dress" -> "portrait photo of a beautiful woman wearing a dress, clear detailed visible human face..."
        if not p.lower().startswith("in ") and not p.lower().startswith("wearing "):
            p = f"wearing {p}"
        enhanced = f"portrait photo of a {subject} {p}, clear detailed visible human face looking directly at camera, sharp focus, 8k resolution, cinematic lighting"

    return enhanced


def swap_face_with_prompt(
    source_bytes: bytes,
    prompt: str,
    engine: str = "auto",
    model: str = "flux",
    width: int = 1024,
    height: int = 1024
) -> tuple[bytes, bytes]:
    """
    1. Detects source face and gender.
    2. Rewrites/enhances the prompt to guarantee a visible human portrait.
    3. Generates the scene using AI.
    4. Swaps user's face onto the generated scene.
    Returns tuple: (swapped_image_bytes, original_generated_bytes)
    """
    app = get_face_analyzer()
    source_img = cv2.imdecode(np.frombuffer(source_bytes, np.uint8), cv2.IMREAD_COLOR)
    if source_img is None:
        raise ValueError("Source photo invalid hai.")

    source_faces = detect_faces_with_fallback(app, source_img)
    if not source_faces:
        raise ValueError("Aapki photo me koi saaf chehra detect nahi hua! Kripya ek achhi lighting aur clear face wali photo bhejein.")

    source_face = sorted(
        source_faces,
        key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]),
        reverse=True
    )[0]

    # Detect gender from source face (0 = female, 1 = male)
    is_female = (getattr(source_face, 'gender', 1) == 0)

    # Intelligently rewrite prompt to guarantee face visibility
    enhanced_prompt = clean_and_enhance_prompt(prompt, is_female)
    logger.info(f"Enhanced prompt for face swap: '{enhanced_prompt}' (gender: {'female' if is_female else 'male'})")

    generated_bytes = None
    if engine in ["pollinations", "auto"]:
        try:
            generated_bytes = pollinations_client.generate_image(
                prompt=enhanced_prompt,
                model=model,
                width=width,
                height=height
            )
        except Exception as pe:
            logger.warning(f"Pollinations prompt generation failed: {pe}")

    if generated_bytes is None and engine in ["aihorde", "auto"]:
        generated_bytes = horde_client.generate_horde_image(
            prompt=enhanced_prompt,
            width=min(width, 512),
            height=min(height, 512)
        )

    if not generated_bytes:
        raise RuntimeError("Prompt se background image generate nahi ho payi. Kripya prompt badal kar try karein.")

    # Swap face onto generated image
    try:
        swapped_bytes = swap_face(source_bytes, generated_bytes)
    except ValueError as ve:
        if "Target photo me koi chehra detect nahi hua" in str(ve):
            raise ValueError(
                "AI dwara banayi gayi photo me chehra detect nahi hua (AI ne sirf dress/body generate ki).\n\n"
                "💡 Tip: Prompt ko is tarah likhein jisme insaan bhi shamil ho:\n"
                "• 'beautiful woman wearing stylish red dress'\n"
                "• 'gorgeous lady in traditional saree'\n"
                "• 'handsome man in royal tuxedo'"
            )
        raise ve

    return swapped_bytes, generated_bytes
