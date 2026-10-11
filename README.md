# CallGuard

CallGuard combines speech-to-text transcription with a rule-based fraud-indicator review workflow.

## Components

- **Frontend:** browser interface served by Nginx on port 8000.
- **API:** FastAPI with Faster-Whisper; receives audio at `/api/transcribe`.
- **Fraud analysis:** configurable keyword and phrase rules in `backend/Stichwortliste.json`.
- **Review history:** SQLite database persisted in a Docker volume.

## Run with Docker Compose

Requirements: Docker Engine and the Docker Compose plugin.

From this directory:

```bash
docker compose up --build
```

Open `http://localhost:8000`.

The first startup downloads the selected Whisper model (`large-v3` by default); this requires an internet connection and can take time. The model is not bundled with this source package. CPU inference can be slow.

To stop:

```bash
docker compose down
```

To stop and remove containers while retaining review history and model cache:

```bash
docker compose down
```

To remove stored review history and the model cache as well, explicitly remove the volumes:

```bash
docker compose down -v
```

## Configuration

Set `WHISPER_MODEL` before starting Compose to choose a Faster-Whisper model supported by the installed package. The default is `large-v3`.

The API accepts WAV, MP3, M4A, FLAC, OGG and WebM files up to 100 MB.

## API endpoints

- `GET /api/health` — service/model status
- `POST /api/transcribe` — transcribe uploaded audio and analyze its segments
- `GET /api/reviews` — list saved review records
- `POST /api/reviews` — save a review record

## Run fraud-rule tests without Docker

Use Python 3.11 or newer. Install the backend requirements, then run:

```bash
python -m pip install -r backend/requirements.txt
PYTHONPATH=backend python tests/test_callguard_fraud.py
PYTHONPATH=backend python tests/test_c15_c16.py
```

## Limitations

This is a decision-support prototype. Keyword matches are indicators for human review, not proof that fraud occurred. A missing match does not establish that a call is safe. Review transcripts and findings in context.

## Project layout

```text
backend/       FastAPI, speech model integration, fraud detector and rules
frontend/      Browser UI
nginx/         Reverse-proxy configuration
tests/         Fraud-rule regression tests
compose.yaml   Multi-container deployment
```
