# Start the MediVoice AI Next.js frontend (development mode)
$ErrorActionPreference = "Stop"
$FrontendDir = Join-Path $PSScriptRoot "..\frontend"

Set-Location $FrontendDir
npm run dev
