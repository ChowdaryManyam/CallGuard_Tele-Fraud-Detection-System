from pathlib import Path
from tempfile import NamedTemporaryFile
from contextlib import asynccontextmanager
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pydantic import BaseModel

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel

FRAUD_MODULE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FRAUD_MODULE_DIR))

from callguard_fraud import analyze_segments

MODEL_SIZE = os.getenv("WHISPER_MODEL", "large-v3")
COMPUTE_TYPE = "int8"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("callguard")

model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    logger.info("Loading Whisper %s on CPU...", MODEL_SIZE)
    model = WhisperModel(
        MODEL_SIZE,
        device="cpu",
        compute_type=COMPUTE_TYPE,
        cpu_threads=8,
    )
    logger.info("Whisper model ready.")
    yield
    model = None


app = FastAPI(title="CallGuard STT API", lifespan=lifespan)

# The frontend is currently served from localhost:8000.
# Keep the API on port 8001 and permit the local frontend during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "model": MODEL_SIZE, "model_loaded": model is not None}


@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    if model is None:
        raise HTTPException(status_code=503, detail="STT model is not ready.")

    filename = Path(audio.filename or "audio.wav").name
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format. Use WAV, MP3, M4A, FLAC, OGG or WebM.",
        )

    temp_path = None
    try:
        size = 0

        # Write to a temporary file, with a size limit.
        with NamedTemporaryFile(
            prefix="callguard_", suffix=extension, delete=False
        ) as temp:
            temp_path = Path(temp.name)

            while True:
                chunk = await audio.read(1024 * 1024)
                if not chunk:
                    break

                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Audio file exceeds the 100 MB upload limit.",
                    )

                temp.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        logger.info("Transcribing uploaded file %s (%d bytes)", filename, size)

        segments, info = model.transcribe(
            str(temp_path),
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        segment_data = []
        text_parts = []

        for segment in segments:
            text = segment.text.strip()
            if text:
                text_parts.append(text)
                segment_data.append({
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": text,
                })

        transcript = " ".join(text_parts).strip()

        fraud_detection = analyze_segments(
            segment_data,
            language="all",
        )
        logger.info(
            "Fraud scan completed: status=%s findings=%d",
            fraud_detection["status"],
            fraud_detection["finding_count"],
        )

        return {
            "audio_file": filename,
            "model": MODEL_SIZE,
            "language_detected": info.language,
            "language_probability": info.language_probability,
            "duration_seconds": info.duration,
            "transcript": transcript,
            "segments": segment_data,
            "fraud_detection": fraud_detection,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Transcription failed for %s", filename)
        raise HTTPException(
            status_code=500,
            detail="Transcription failed. Check the backend terminal logs.",
        )
    finally:
        await audio.close()
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                logger.warning("Could not remove temporary file %s", temp_path)


# Persistent CallGuard review history.
DB_PATH = Path(os.getenv("CALLGUARD_DB_PATH", str(Path(__file__).with_name("callguard_reviews.sqlite3"))))
VALID_ASSESSMENTS = {"Review", "False alarm", "Fraud detected"}

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_reviews_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                assessment TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL
            )
        """)

init_reviews_db()

class ReviewInput(BaseModel):
    name: str = "Unnamed recording"
    assessment: str
    comment: str = ""
    date: str = ""

@app.get("/api/reviews")
def list_reviews():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, assessment, comment, date "
            "FROM reviews ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]

@app.post("/api/reviews")
def save_review(review: ReviewInput):
    if review.assessment not in VALID_ASSESSMENTS:
        raise HTTPException(status_code=400, detail="Invalid assessment.")
    if len(review.name) > 500 or len(review.comment) > 500:
        raise HTTPException(status_code=400, detail="Review text is too long.")

    date = review.date or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO reviews (name, assessment, comment, date) "
            "VALUES (?, ?, ?, ?)",
            (review.name or "Unnamed recording", review.assessment,
             review.comment, date),
        )
        row = conn.execute(
            "SELECT id, name, assessment, comment, date FROM reviews WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)
