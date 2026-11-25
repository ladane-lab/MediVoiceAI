# MediVoice AI — Voice-Based Doctor Appointment Assistant

MediVoice AI is a healthcare appointment assistant built with a decoupled **Next.js (JavaScript JSX)** frontend and a **Python FastAPI** backend. It provides SQLite-backed doctor schedules, dynamic slot generation, transactional booking/cancellation APIs, and a **Pipecat** real-time voice agent using **SmallWebRTC**, **ElevenLabs STT/TTS**, and **Google Gemini** function calling.

> **Current Status:** **Phase 1–4 Complete (Backend Voice Pipeline & APIs Ready; Frontend Redesign in Phase 5)**.

---

## Project Structure

```text
MediVoiceAI/
├── frontend/                     # Next.js (App Router, JSX, Tailwind CSS, Lucide Icons)
│   ├── src/
│   │   ├── app/
│   │   │   ├── globals.css
│   │   │   ├── layout.js
│   │   │   └── page.js           # Phase 1 clinical dashboard & live backend health view
│   │   ├── components/
│   │   │   ├── BackendHealthCard.jsx
│   │   │   ├── Navbar.jsx
│   │   │   └── PhaseRoadmap.jsx
│   │   └── lib/
│   │       └── api.js
│   ├── .env.example
│   └── package.json
├── backend/                      # Python FastAPI + SQLAlchemy + Pipecat Voice Agent
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py             # Environment variable loader (pydantic-settings)
│   │   ├── database.py           # SQLite engine, PRAGMA foreign_keys, SessionLocal
│   │   ├── main.py               # FastAPI app, lifespan DB seed & voice shutdown
│   │   ├── models.py             # Doctor, Patient, Appointment ORM models & indexes
│   │   ├── schemas.py            # Pydantic schemas for doctors, appointments, voice
│   │   ├── seed.py               # Idempotent seeding of 6 fictional doctors
│   │   ├── routes/
│   │   │   ├── doctors.py        # GET /api/doctors, /{id}, /{id}/availability
│   │   │   ├── appointments.py   # POST /book, GET /appointments, POST /{id}/cancel
│   │   │   └── voice.py          # Pipecat SmallWebRTC voice session & SDP endpoints
│   │   ├── services/
│   │   │   ├── availability.py   # Dynamic 24-hour slot generation
│   │   │   └── appointment_service.py # Shared appointment logic (FastAPI + Pipecat)
│   │   └── voice/
│   │       ├── __init__.py
│   │       ├── agent.py          # Pipecat Pipeline, Silero VAD, Gemini, ElevenLabs
│   │       ├── prompts.py        # Voice-optimized clinical system prompt
│   │       ├── session.py        # SmallWebRTCRequestHandler & session manager
│   │       └── tools.py          # Gemini function-calling tools & confirmation state
│   ├── tests/
│   │   ├── test_appointments.py  # Phase 3 appointment API & DB tests (11 tests)
│   │   └── test_voice_agent.py   # Phase 4 voice tool, state gate & mocked pipeline tests
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py
├── scripts/
│   ├── dev-backend.ps1
│   └── dev-frontend.ps1
├── .env.example
├── .gitignore
└── README.md
```

---

## Voice Architecture (Phase 4)

The backend uses **Pipecat `1.17.0`** with **`SmallWebRTCTransport`** (`aiortc`) to stream bidirectional browser audio without requiring an external third-party SFU service:

```text
Browser Microphone (WebRTC Audio)
  -> SmallWebRTCTransport.input()
  -> ElevenLabsRealtimeSTTService (scribe_v2_realtime)
  -> UserTurnTranscriptObserver (tracks real caller turns for confirmation gates)
  -> LLMContextAggregatorPair.user() + SileroVADAnalyzer
  -> GoogleLLMService (Gemini + ToolsSchema function calling)
  -> ElevenLabsTTSService (eleven_flash_v2_5)
  -> SmallWebRTCTransport.output()
  -> Browser Speaker (WebRTC Audio)
```

### Browser-to-Pipecat Signaling Flow

1. `GET /api/voice/status` — Checks whether `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_VOICE_ID` are configured (returns non-secret readiness info).
2. `POST /api/voice/sessions` — Pre-registers a voice session ID and returns ICE server configuration (returns HTTP `503` if API keys are missing).
3. `POST /api/voice/offer` — Accepts the browser's WebRTC SDP offer (`sdp`, `type`, optional `pc_id` / `session_id`), starts the Pipecat pipeline, and returns the WebRTC SDP answer.
4. `PATCH /api/voice/offer` — Accepts trickle ICE candidates (`pc_id`, `candidates`).
5. `POST /api/voice/sessions/{session_id}/end` — Cancels the Pipecat `PipelineTask` and closes the WebRTC peer connection.

### Gemini Function Calling & Confirmation Enforcement

Gemini can invoke 7 tools defined in `backend/app/voice/tools.py`:
- `list_doctors`
- `check_doctor_availability`
- `confirm_phone_number`
- `book_appointment`
- `list_appointments`
- `confirm_cancellation`
- `cancel_appointment`

All appointment operations call the Phase 3 functions in `backend/app/services/appointment_service.py` directly—no business logic is duplicated.

To prevent Gemini from skipping safety steps, **`VoiceConversationState`** enforces both confirmations in Python code:
1. **Phone-Number Confirmation Gate:** Calling `book_appointment`, `list_appointments`, or `cancel_appointment` without a confirmed phone number in session state is blocked. `confirm_phone_number` first stages the normalized E.164 number and returns a digit-by-digit readback; only after a subsequent caller speech turn (`UserTurnTranscriptObserver`) and explicit confirmation does the state unlock.
2. **Cancellation Confirmation Gate:** Cancelling requires both a confirmed caller phone number and a two-step appointment confirmation (`confirm_cancellation`) that stages the appointment details for readback and waits for explicit caller approval on a subsequent turn.

---

## Required API Keys & `.env` Setup

1. Copy the template files (never commit `.env` or `.env.local`):

   ```powershell
   Copy-Item .env.example .env
   Copy-Item frontend\.env.example frontend\.env.local
   ```

2. Set these required variables in `.env` (or `backend/.env`):
   - `GEMINI_API_KEY` — Google Gemini API key (used by `GoogleLLMService`)
   - `ELEVENLABS_API_KEY` — ElevenLabs API key (used by `ElevenLabsRealtimeSTTService` and `ElevenLabsTTSService`)
   - `ELEVENLABS_VOICE_ID` — ElevenLabs voice ID for assistant speech output

   Optional voice configuration:
   - `GEMINI_MODEL` (default: `gemini-2.5-flash`)
   - `VOICE_ICE_SERVERS` (default: `stun:stun.l.google.com:19302`)

If any required credential is missing or still a placeholder, `/api/voice/sessions` and `/api/voice/offer` return a clear `503` JSON error rather than crashing.

---

## Running the Applications & Tests

### Start the Python Backend (Port `8000`)

```powershell
cd D:\MediVoiceAI\backend
.\.venv\Scripts\python.exe run.py
```

- Swagger UI: `http://localhost:8000/docs`
- Health endpoint: `http://localhost:8000/health`
- Voice readiness: `http://localhost:8000/api/voice/status`

### Start the Next.js Frontend (Port `3000`)

```powershell
cd D:\MediVoiceAI\frontend
npm run dev
```

### Run Automated Backend Tests

```powershell
cd D:\MediVoiceAI\backend
.\.venv\Scripts\python.exe -m pytest -v
```

---

## Real vs. Mocked / Credential-Gated Integrations

- **Real & Verified:** FastAPI REST APIs, SQLite + SQLAlchemy models/constraints, 6 seeded doctors, dynamic slot availability, transactional booking/cancellation, phone-confirmation and cancellation-confirmation state enforcement, and missing-credential `503` handling.
- **Mocked in Automated Tests:** External `GoogleLLMService`, `ElevenLabsRealtimeSTTService`, `ElevenLabsTTSService`, `SileroVADAnalyzer`, and `SmallWebRTCTransport` calls are mocked in `backend/tests/test_voice_agent.py` so no paid external API calls are made during tests.
- **Requires Credentials & Browser UI (Phase 5):** Live browser-to-Pipecat audio streaming requires valid `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_VOICE_ID` values in `.env`, plus the Phase 5 frontend WebRTC client UI (planned next).
