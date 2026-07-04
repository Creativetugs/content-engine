# MoneySense Content Engine — first-time local setup
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== MoneySense Content Engine — Local Setup ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

if (-not (Get-Content ".env" | Select-String "OPENAI_API_KEY=sk-")) {
    Write-Host ""
    Write-Host "IMPORTANT: Open .env and set OPENAI_API_KEY=your-key-here" -ForegroundColor Yellow
    Write-Host "File: $PSScriptRoot\.env"
    Write-Host ""
}

if (-not (Test-Path "venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv venv
}

Write-Host "Installing dependencies (local — OpenAI transcription, no PyTorch)..."
& ".\venv\Scripts\pip.exe" install -r requirements-local.txt -q

New-Item -ItemType Directory -Force -Path uploads, output, "output\images" | Out-Null

Write-Host ""
Write-Host "Setup complete. Start the API with:" -ForegroundColor Green
Write-Host "  .\run-api.bat"
Write-Host ""
Write-Host "Then open:" -ForegroundColor Green
Write-Host "  http://127.0.0.1:8001/docs"
Write-Host "  http://127.0.0.1:8001/health"
