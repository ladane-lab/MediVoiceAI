# MediVoice AI — Voice-Based Doctor Appointment Assistant

MediVoice AI is a healthcare appointment assistant built with a decoupled **Next.js (JavaScript JSX)** frontend and a **Python FastAPI** backend, preparing for real-time **WebRTC** voice conversations powered by **Pipecat**, **ElevenLabs (STT/TTS)**, **Google Gemini**, and **SQLite**.

> **Current Status:** **Phase 1 — Foundation** (Frontend & backend initialization, environment configuration, and live health check). Appointment booking and the voice pipeline are intentionally not implemented yet and will be added in Phase 2+.

---

## Project Structure

```text
MediVoiceAI/
├── frontend/                 # Next.js (App Router, JSX, Tailwind CSS, Lucide Icons)
│   ├── src/
│   │   ├── app/
│   │   │   ├── globals.css
│   │   │   ├── layout.js
│   │   │   └── page.js       # Phase 1 clinical dashboard & live backend health view
│   │   ├── components/
│   │   │   ├── BackendHealthCard.jsx
│   │   │   ├── Navbar.jsx
│   │   │   └── PhaseRoadmap.jsx
│   │   └── lib/
│   │       └── api.js        # Backend API helper
│   ├── .env.example
│   └── package.json
├── backend/                  # Python FastAPI server
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py         # Environment variable loader (pydantic-settings)
│   │   └── main.py           # FastAPI app with / and /health endpoints
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py                # Uvicorn development launcher
├── scripts/                  # PowerShell helper scripts for Windows
│   ├── dev-backend.ps1
│   └── dev-frontend.ps1
├── .env.example
├── .gitignore
└── README.md
```

---

## Environment Setup

1. Copy `.env.example` to `.env` at the project root (or configure `backend/.env` and `frontend/.env.local`):

   ```powershell
   Copy-Item .env.example .env
   Copy-Item frontend\.env.example frontend\.env.local
   ```

2. Never commit `.env` or `.env.local` files. Real `GEMINI_API_KEY` and `ELEVENLABS_API_KEY` values will be required starting in Phase 2 when AI voice features are enabled.

---

## Running the Applications

Open **two terminals** from `D:\MediVoiceAI`:

### 1. Start the Python Backend (FastAPI on port `8000`)

```powershell
cd D:\MediVoiceAI\backend
.\.venv\Scripts\python.exe run.py
```

Or using the helper script:

```powershell
.\scripts\dev-backend.ps1
```

- API root: `http://localhost:8000`
- Health endpoint: `http://localhost:8000/health`
- Swagger docs: `http://localhost:8000/docs`

### 2. Start the Next.js Frontend (on port `3000`)

```powershell
cd D:\MediVoiceAI\frontend
npm run dev
```

Or using the helper script:

```powershell
.\scripts\dev-frontend.ps1
```

- Frontend UI: `http://localhost:3000`
