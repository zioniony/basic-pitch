"""FastAPI application that converts audio to MIDI locally using basic-pitch.

All audio is processed on the machine running this server. No audio is ever
sent to the internet. The basic-pitch model is bundled with the package, so
even model loading is fully offline.
"""

from __future__ import annotations

import io
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import uuid

from typing import Annotated, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Silence TensorFlow's chatty C++ logging before we import anything that pulls
# in TF. basic-pitch[tf] imports tensorflow lazily, but setting these here is
# harmless and keeps the console readable.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

from basic_pitch import ICASSP_2022_MODEL_PATH  # noqa: E402
from basic_pitch.inference import Model, predict  # noqa: E402

logger = logging.getLogger("basic_pitch_local")

BASE_DIR = pathlib.Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Audio formats basic-pitch (via librosa/audioread) can typically handle.
ALLOWED_EXTS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    ".webm", ".opus", ".aiff", ".aif", ".wma",
}

app = FastAPI(title="Basic Pitch Local", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Model handling. The ICASSP 2022 model ships inside the basic-pitch package,
# so loading it never touches the network.
# ---------------------------------------------------------------------------
_model: Optional[Model] = None


def get_model() -> Model:
    """Load the bundled basic-pitch model once and reuse it."""
    global _model
    if _model is None:
        logger.info("Loading basic-pitch model (one-time, local)...")
        _model = Model(ICASSP_2022_MODEL_PATH)
        logger.info("Model ready.")
    return _model


def normalize_to_wav(src: pathlib.Path) -> pathlib.Path:
    """Convert arbitrary audio to a 22.05kHz mono wav when ffmpeg is present.

    basic-pitch resamples to 22050Hz mono internally anyway, so converting up
    front guarantees librosa can read the file (especially browser-recorded
    webm/opus) and skips a second decode. Falls back to the original file if
    ffmpeg is unavailable.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return src
    wav_path = src.with_suffix(".normalized.wav")
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", str(src),
                "-ar", "22050", "-ac", "1",
                str(wav_path),
            ],
            check=True,
            capture_output=True,
        )
        return wav_path
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("ffmpeg normalization failed (%s); using original", exc)
        return src


def run_conversion(
    audio_path: pathlib.Path,
    onset_threshold: float,
    frame_threshold: float,
    min_note_length: float,
    min_frequency: Optional[float],
    max_frequency: Optional[float],
    midi_tempo: float,
) -> bytes:
    """Run basic-pitch on a local file and return the MIDI bytes."""
    wav_path = normalize_to_wav(audio_path)
    try:
        _model_output, midi_data, _note_events = predict(
            wav_path,
            get_model(),
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=min_note_length,
            minimum_frequency=min_frequency,
            maximum_frequency=max_frequency,
            midi_tempo=midi_tempo,
        )
    except Exception as exc:
        logger.exception("Conversion failed")
        raise HTTPException(status_code=422, detail=f"Conversion failed: {exc}") from exc

    buf = io.BytesIO()
    midi_data.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    onset_threshold: Annotated[float, Form(ge=0.05, le=0.95)] = 0.5,
    frame_threshold: Annotated[float, Form(ge=0.05, le=0.95)] = 0.3,
    min_note_length: Annotated[float, Form(ge=3, le=50)] = 11,
    min_pitch: Annotated[float, Form(ge=0, le=2000)] = 0,
    max_pitch: Annotated[float, Form(ge=40, le=3000)] = 3000,
    midi_tempo: Annotated[float, Form(ge=24, le=224)] = 120,
):
    """Convert an uploaded audio file to MIDI entirely on this machine."""
    original_name = pathlib.Path(file.filename or "audio").name
    stem = pathlib.Path(original_name).stem or "audio"
    ext = pathlib.Path(original_name).suffix.lower()

    if ext and ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTS))}",
        )

    # Stream the upload to a local temp file. It never leaves this machine.
    suffix = ext or ".bin"
    tmp_path = pathlib.Path(tempfile.gettempdir()) / f"bpl_{uuid.uuid4().hex}{suffix}"
    try:
        with tmp_path.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                fh.write(chunk)

        midi_bytes = run_conversion(
            tmp_path,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            min_note_length=min_note_length,
            min_frequency=min_pitch if min_pitch > 0 else None,
            max_frequency=max_pitch,
            midi_tempo=midi_tempo,
        )
    finally:
        # Clean up the uploaded audio and any normalized wav immediately. We
        # do not retain user audio on disk.
        for p in (tmp_path, tmp_path.with_suffix(".normalized.wav")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem) or "audio"
    return Response(
        content=midi_bytes,
        media_type="audio/midi",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_stem}.mid"',
        },
    )


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/convert"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def run() -> None:
    """Entry point for the `basic-pitch-local` console script."""
    import uvicorn

    host = os.environ.get("BPL_HOST", "127.0.0.1")
    port = int(os.environ.get("BPL_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
