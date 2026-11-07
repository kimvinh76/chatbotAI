# Script khoi dong ung dung Tro Ly AI Cham Thi Tin Hoc THPT
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  DANG KHOI DONG TRO LY AI CHAM THI TIN HOC THPT" -ForegroundColor Green
Write-Host "  Truy cap trinh duyet tai: http://localhost:8501" -ForegroundColor Yellow
Write-Host "===================================================" -ForegroundColor Cyan
Set-Location -Path $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\streamlit.exe" run "$PSScriptRoot\app.py"

