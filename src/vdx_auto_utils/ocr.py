"""Captcha OCR via Gemini vision models and OpenCV preprocessing."""

from __future__ import annotations

import base64
import binascii
import logging
import mimetypes
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import requests
from google import genai
from google.api_core import exceptions as google_exceptions
from google.genai import types

ALLOWLIST = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
UPSCALE_FACTOR = 3
BORDER_PAD = 20
MAJORITY_THRESHOLD = 3
IMAGE_FETCH_TIMEOUT = 30

_UNSET = object()

CAPTCHA_PROMPT = (
    "This is a captcha image. "
    "Read the characters and reply with ONLY the "
    "alphanumeric text, uppercase, no spaces, "
    "no explanation, nothing else."
)

_NOISY_LOGGERS = ("google_genai", "google.genai", "httpx", "httpcore", "urllib3")


class CaptchaRecognizer:
    """
    Recognize alphanumeric captcha text using Gemma vision + OpenCV.

    Args:
        api_key: Google Gemini API key.
        model: Google model id (e.g. ``gemma-4-31b-it``).
        expected_length: Captcha length for ensemble voting. Omit to accept any length
            from the first pass (no ensemble).
        max_retries: Retries on transient 500 errors from the API.
        retry_delay: Seconds between retries.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        expected_length: Optional[int] = None,
        max_retries: int = 5,
        retry_delay: int = 10,
    ):
        self.api_key = api_key
        self.model = model
        self.expected_length = expected_length
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: Optional[genai.Client] = None

    @staticmethod
    def _mime_from_bytes(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data[:2] == b"\xff\xd8":
            return "image/jpeg"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
            return "image/webp"
        return "image/png"

    @staticmethod
    def _bytes_to_data_uri(data: bytes, mime: Optional[str] = None) -> str:
        resolved = mime or CaptchaRecognizer._mime_from_bytes(data)
        if not resolved.startswith("image/"):
            resolved = CaptchaRecognizer._mime_from_bytes(data)
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{resolved};base64,{encoded}"

    @staticmethod
    def _silence_noisy_loggers() -> None:
        """Lower third-party SDK log levels without changing app-wide logging config."""
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.ERROR)

    def _log(self, verbose: bool, message: str, *args) -> None:
        if verbose:
            print(message % args if args else message)

    def _emit_processing(self, verbose: bool) -> None:
        if not verbose:
            print("Processing captcha...")

    def _emit_success(self, verbose: bool, result: str) -> None:
        if verbose:
            self._log(verbose, "Result: '%s'", result)
        else:
            print(result)

    def _emit_failure(self, verbose: bool, exc: Exception) -> None:
        message = f"Captcha recognition failed: {exc}"
        if verbose:
            self._log(verbose, "%s", message)
        else:
            print(message)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @staticmethod
    def clean_result(text: str) -> str:
        normalized = text.upper().replace(" ", "")
        return "".join(c for c in normalized if c in ALLOWLIST)

    @staticmethod
    def to_data_uri(image: str, timeout: int = IMAGE_FETCH_TIMEOUT) -> str:
        """
        Normalize image input to a ``data:image/...;base64,...`` URI.

        Accepts a data URI, http(s) image URL, file path, or raw base64 image bytes.
        """
        stripped = image.strip()
        if stripped.startswith("data:image"):
            return stripped

        if stripped.lower().startswith(("http://", "https://")):
            response = requests.get(stripped, timeout=timeout)
            response.raise_for_status()
            content_type = (
                response.headers.get("Content-Type", "").split(";")[0].strip()
            )
            mime = content_type if content_type.startswith("image/") else None
            data = response.content
            arr = np.frombuffer(data, dtype=np.uint8)
            if cv2.imdecode(arr, cv2.IMREAD_COLOR) is None:
                raise ValueError(f"URL did not return a decodable image: {stripped}")
            return CaptchaRecognizer._bytes_to_data_uri(data, mime)

        path = Path(stripped)
        if path.is_file():
            data = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0]
            return CaptchaRecognizer._bytes_to_data_uri(data, mime)

        try:
            raw = base64.b64decode(stripped, validate=False)
        except binascii.Error:
            raw = b""

        if raw:
            arr = np.frombuffer(raw, dtype=np.uint8)
            if cv2.imdecode(arr, cv2.IMREAD_COLOR) is not None:
                return CaptchaRecognizer._bytes_to_data_uri(raw)

        raise ValueError(
            "image must be a data URI, http(s) URL, file path, or valid base64 image data"
        )

    @staticmethod
    def decode_data_uri(data_uri: str) -> np.ndarray:
        if not data_uri.startswith("data:image"):
            raise ValueError("data_uri must start with 'data:image'")
        _, encoded = data_uri.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode data URI image")
        return img

    @staticmethod
    def img_to_bytes(img: np.ndarray) -> bytes:
        _, buf = cv2.imencode(".png", img)
        return buf.tobytes()

    def _upscale(self, img: np.ndarray) -> np.ndarray:
        return cv2.resize(
            img,
            None,
            fx=UPSCALE_FACTOR,
            fy=UPSCALE_FACTOR,
            interpolation=cv2.INTER_CUBIC,
        )

    def _to_gray(self, img: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(self._upscale(img), cv2.COLOR_BGR2GRAY)

    def _pad_and_to_bgr(self, gray: np.ndarray) -> np.ndarray:
        padded = cv2.copyMakeBorder(
            gray,
            BORDER_PAD,
            BORDER_PAD,
            BORDER_PAD,
            BORDER_PAD,
            cv2.BORDER_CONSTANT,
            value=255,
        )
        return cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)

    def preprocess(self, img: np.ndarray) -> np.ndarray:
        gray = self._to_gray(img)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
        sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(denoised, -1, sharpen_kernel)
        thresh = cv2.adaptiveThreshold(
            sharpened,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        cleaned = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((1, 1), np.uint8))
        return self._pad_and_to_bgr(cleaned)

    def get_variants(self, img: np.ndarray) -> List[np.ndarray]:
        gray = self._to_gray(img)

        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        adaptive = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )

        return [
            self._pad_and_to_bgr(gray),
            self._pad_and_to_bgr(otsu),
            self._pad_and_to_bgr(adaptive),
            self.preprocess(img),
        ]

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if isinstance(exc, google_exceptions.InternalServerError):
            return True
        msg = str(exc)
        return "500" in msg or "Internal error encountered" in msg

    def _generate_captcha_text(self, img: np.ndarray) -> str:
        response = self._get_client().models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_bytes(
                    data=self.img_to_bytes(img), mime_type="image/png"
                ),
                types.Part.from_text(text=CAPTCHA_PROMPT),
            ],
        )
        return self.clean_result(response.text)

    def read_variant(self, img: np.ndarray) -> str:
        """Send one preprocessed image variant to Gemma; retry on transient 500 errors."""
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._generate_captcha_text(img)
            except Exception as exc:
                if not self._is_retryable_error(exc) or attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_delay)

    def character_level_vote(
        self, candidates: List[str], length: int, verbose: bool
    ) -> str:
        valid = [c for c in candidates if len(c) == length]
        if not valid:
            return max(candidates, key=len)

        result = []
        for i in range(length):
            chars_at_pos = [c[i] for c in valid]
            tally = Counter(chars_at_pos)
            winner, count = tally.most_common(1)[0]
            self._log(
                verbose,
                "Pos %s: %s -> '%s' (%s/%s)",
                i,
                dict(tally),
                winner,
                count,
                len(valid),
            )
            result.append(winner)

        final = "".join(result)
        self._log(verbose, "Character vote result: '%s'", final)
        return final

    def _recognize_image(
        self,
        img: np.ndarray,
        verbose: bool,
        expected_length: Optional[int],
    ) -> str:
        length = expected_length

        result = self.read_variant(self.get_variants(img)[0])
        self._log(verbose, "Single-pass: '%s' (length %d)", result, len(result))
        if length is None:
            return result
        if len(result) == length:
            return result

        self._log(
            verbose,
            "Length mismatch (got %d, expected %d), running ensemble",
            len(result),
            length,
        )
        variants = self.get_variants(img)
        candidates = [self.read_variant(variant) for variant in variants]
        self._log(verbose, "Candidates: %s", candidates)

        winner = self._majority_vote(candidates, length)
        if winner is not None:
            count = sum(1 for c in candidates if c == winner)
            self._log(
                verbose,
                "Majority vote: '%s' (%s/%s)",
                winner,
                count,
                len(candidates),
            )
            return winner

        self._log(verbose, "Character-level vote")
        return self.character_level_vote(candidates, length, verbose)

    def _majority_vote(
        self, candidates: List[str], expected_length: int
    ) -> Optional[str]:
        length_filtered = [c for c in candidates if len(c) == expected_length]
        if not length_filtered:
            return None
        top, top_count = Counter(length_filtered).most_common(1)[0]
        if top_count >= MAJORITY_THRESHOLD:
            return top
        return None

    def recognize(
        self,
        data_uri: str,
        expected_length: Optional[int] | object = _UNSET,
        verbose: bool = False,
    ) -> str:
        """
        Recognize captcha text from image data.

        Args:
            data_uri: ``data:image/...`` URI, http(s) URL, file path, or raw base64 string.
            expected_length: Captcha length for ensemble voting. Omit to use the instance
                default; pass ``None`` to skip length checks and return the first pass.
            verbose: When True, print recognition steps to stdout; otherwise print a
                processing message, then the final result or a failure message.

        Returns:
            Uppercase alphanumeric captcha string.
        """
        length = self.expected_length if expected_length is _UNSET else expected_length
        self._silence_noisy_loggers()
        self._emit_processing(verbose)
        try:
            img = self.decode_data_uri(self.to_data_uri(data_uri))
            result = self._recognize_image(img, verbose, length)
            self._emit_success(verbose, result)
            return result
        except Exception as exc:
            self._emit_failure(verbose, exc)
            raise


def recognize_captcha(
    api_key: str,
    model: str,
    image: str,
    expected_length: Optional[int] = None,
    verbose: bool = False,
) -> str:
    """
    Recognize captcha text in one call.

    Args:
        api_key: Google Gemini API key.
        model: Gemini model id (e.g. ``gemma-4-31b-it``).
        image: ``data:image/...`` URI, http(s) URL, file path, or raw base64 string.
        expected_length: Captcha character count for ensemble voting. Omit for any length
            (single API call only).
        verbose: When True, print recognition steps to stdout; otherwise print a
            processing message, then the final result or a failure message.

    Example:
        from vdx_auto_utils import recognize_captcha

        text = recognize_captcha(
            api_key="...",
            model="gemma-4-31b-it",
            image="data:image/png;base64,...",
            verbose=False,
        )
    """
    recognizer = CaptchaRecognizer(
        api_key=api_key,
        model=model,
        expected_length=expected_length,
    )
    return recognizer.recognize(
        image,
        expected_length=expected_length,
        verbose=verbose,
    )
