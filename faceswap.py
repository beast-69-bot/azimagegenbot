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
    source_faces = app.get(source_img)
    if not source_faces:
        raise ValueError("Source photo me koi saaf chehra detect nahi hua! Kripya kisi aisi photo bhejein jisme chehra saaf dikh raha ho.")

    # Select largest face in source
    source_face = sorted(
        source_faces,
        key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]),
        reverse=True
    )[0]

    # Detect faces in target
    target_faces = app.get(target_img)
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


def swap_face_with_prompt(
    source_bytes: bytes,
    prompt: str,
    engine: str = "auto",
    model: str = "flux",
    width: int = 1024,
    height: int = 1024
) -> tuple[bytes, bytes]:
    """
    1. Generates an image scene matching the prompt.
    2. Swaps user's face onto the generated scene.
    Returns tuple: (swapped_image_bytes, original_generated_bytes)
    """
    # Verify source face first so we don't waste generation time if face isn't detectable
    app = get_face_analyzer()
    source_img = cv2.imdecode(np.frombuffer(source_bytes, np.uint8), cv2.IMREAD_COLOR)
    if source_img is None:
        raise ValueError("Source photo invalid hai.")
    source_faces = app.get(source_img)
    if not source_faces:
        raise ValueError("Aapki photo me koi saaf chehra detect nahi hua! Kripya ek achhi lighting aur clear face wali photo bhejein.")

    # Append prompt enhancement to ensure a clear human face is generated in the scene
    enhanced_prompt = f"{prompt}, close up portrait photo, clear detailed visible human face looking at camera, 8k masterpiece"

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
    swapped_bytes = swap_face(source_bytes, generated_bytes)
    return swapped_bytes, generated_bytes
