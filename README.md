# MediVoice AI — Voice-Based Doctor Appointment Assistant

MediVoice AI is a full-stack healthcare appointment assistant built with a **Next.js (JavaScript JSX + Tailwind CSS)** dashboard and a **Python FastAPI** backend. It includes SQLite appointment scheduling, dynamic slot generation, transactional booking/cancellation APIs, and a real-time **Pipecat** voice agent powered by **SmallWebRTC**, **ElevenLabs STT/TTS**, and **Google Gemini** function calling.

---

## Project Structure

```text
MediVoiceAI/
├── frontend/                     # Next.js (App Router, JSX, Tailwind CSS, Lucide Icons)
│   ├── src/
│   │   ├── app/
│   │   │   ├── globals.css
│   │   │   ├── layout.js
│   │   │   └── page.js           # Clinical dashboard + sidebar + persistent WebRTC audio
│   │   ├── components/
│   │   │   ├── AppointmentsSection.jsx
│   │   │   ├── DoctorsSection.jsx
│   │   │   ├── Navbar.jsx
│   │   │   ├── Sidebar.jsx
│   │   │   ├── SummaryCards.jsx
│   │   │   └── VoiceAssistantCard.jsx
│   │   ├── hooks/
│   │   │   └── useVoiceCall.js   # Browser RTCPeerConnection, DataChannel & audio meter
│   │   └── lib/
│   │       └── api.js            # Reusable REST & WebRTC signaling client
│   ├── .env.example
│   └── package.json
├── backend/                      # Python FastAPI + SQLAlchemy + Pipecat Voice Agent
│   ├── app/
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
│   │       ├── agent.py          # Pipecat Pipeline, Transcript Observers, Gemini, ElevenLabs
│   │       ├── prompts.py        # Voice-optimized clinical system prompt
│   │       ├── session.py        # SmallWebRTCRequestHandler & session manager
│   │       └── tools.py          # Gemini tools & explicit confirmation state machine
│   ├── tests/
│   │   ├── test_appointments.py  # Phase 3 appointment API & DB tests (11 tests)
│   │   └── test_voice_agent.py   # Phase 4/5 voice tool, confirmation & pipeline tests
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

## Installation

### 1. Backend Dependencies (Python `3.11+`, tested on `3.14.3`)

```powershell
cd D:\MediVoiceAI\backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Frontend Dependencies (Node.js)

```powershell
cd D:\MediVoiceAI\frontend
npm install
```

---

## Environment Configuration

1. Copy the template files (never commit `.env` or `.env.local`):

   ```powershell
   Copy-Item .env.example .env
   Copy-Item frontend\.env.example frontend\.env.local
   ```

2. Set your backend credentials in `D:\MediVoiceAI\.env`:
   - `GEMINI_API_KEY` — Google Gemini API key
   - `ELEVENLABS_API_KEY` — ElevenLabs API key (used for both STT & TTS)
   - `ELEVENLABS_VOICE_ID` — ElevenLabs voice ID for spoken assistant responses
   - `GEMINI_MODEL` — Optional (default: `gemini-2.5-flash`)
   - `VOICE_ICE_SERVERS` — Optional STUN/TURN URLs (default: `stun:stun.l.google.com:19302`)

3. Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `D:\MediVoiceAI\frontend\.env.local`. Never place Gemini or ElevenLabs API keys in `NEXT_PUBLIC_*` variables.

---

## Starting Both Servers & Opening the Dashboard

Run in **two terminals**:

**Terminal 1 — FastAPI Backend (`http://localhost:8000`):**
```powershell
cd D:\MediVoiceAI\backend
.\.venv\Scripts\python.exe run.py
```

**Terminal 2 — Next.js Frontend (`http://localhost:3000`):**
```powershell
cd D:\MediVoiceAI\frontend
npm run dev
```

Open `http://localhost:3000` in Chrome, Edge, or Firefox to use the dashboard:
- **Dashboard:** Overview cards, live Voice Assistant card, doctors directory, and phone-number appointment lookup.
- **Find Doctors:** Filter by speciality and click any doctor to check real-time 24-hour slot availability by date.
- **My Appointments:** Demo mode without login — enter your phone number (e.g. `+919876543210`) to view appointments and cancel booked visits with explicit phone confirmation.
- **Voice Assistant:** Full-view WebRTC call interface with mute/unmute, call duration, real microphone level meter, and live caller/assistant transcripts.

---

## WebRTC Connection & Transcript Architecture

1. Clicking **Start Call** requests browser microphone access (`navigator.mediaDevices.getUserMedia`)—never on page load.
2. Frontend calls `POST /api/voice/sessions` to verify backend credentials and obtain `session_id` + ICE servers.
3. `useVoiceCall.js` creates an `RTCPeerConnection`, attaches the microphone track, opens a WebRTC DataChannel (`medivoice`), creates an SDP offer, and sends it to `POST /api/voice/offer` (plus trickle ICE via `PATCH /api/voice/offer`).
4. Pipecat's `SmallWebRTCTransport` streams bidirectional audio through:
   `ElevenLabsRealtimeSTTService` → `UserTurnTranscriptObserver` → `SileroVADAnalyzer` → `GoogleLLMService` (with 7 appointment tools) → `AssistantEventsObserver` → `ElevenLabsTTSService` → `BotSpeakingObserver` → browser `<audio>` element.
5. `UserTurnTranscriptObserver` and `AssistantEventsObserver` push deduplicated transcript and speaking-activity JSON messages over the WebRTC DataChannel (with `GET /api/voice/sessions/{session_id}` fallback), and emit `appointment_updated` after bookings/cancellations so the dashboard refreshes automatically.
6. Clicking **End Call** (or leaving the page) closes `RTCPeerConnection`, stops local microphone tracks, and calls `POST /api/voice/sessions/{session_id}/end`.

### Browser Microphone Requirements

- Browsers allow `getUserMedia` microphone access only on **secure contexts**: `http://localhost:3000` or `https://...` (not `http://<lan-ip>:3000`).
- Grant microphone permission when prompted by your browser.

---

## Confirmation Security Safeguards

In `backend/app/voice/tools.py`, `VoiceConversationState` enforces both confirmation gates in Python code:
- **Phone Confirmation:** `book_appointment`, `list_appointments`, and `cancel_appointment` cannot execute until `confirm_phone_number` stages the normalized number for digit-by-digit readback AND a subsequent non-empty caller transcript (`UserTurnTranscriptObserver`) matches an explicit affirmative (`is_explicit_affirmative`) without negative/hesitation words. Unrelated questions, silence, rejections, or Gemini passing `caller_confirmed=true` alone are rejected. Speaking a different phone number resets confirmation.
- **Cancellation Confirmation:** Requires both a confirmed caller phone number and a staged appointment readback followed by a *new* explicit affirmative caller utterance before calling `appointment_service.cancel_appointment(..., phone_number_confirmed=True)`.

---

## Running Automated Tests

```powershell
cd D:\MediVoiceAI\backend
.\.venv\Scripts\python.exe -m pytest -v
```

```powershell
cd D:\MediVoiceAI\frontend
npm run lint
npm run build
```

---

## Known Limitations

- **Demo Phone Lookup:** Appointments have no login/OTP; callers identify themselves by speaking or entering their phone number.
- **In-Memory Voice Sessions:** Active WebRTC session records are stored in backend process memory (`VoiceSessionManager`).
- **Automated Test Mocking:** `test_voice_agent.py` mocks external Gemini, ElevenLabs, and WebRTC transport calls; live audio calls require valid backend credentials and an interactive browser microphone session.
