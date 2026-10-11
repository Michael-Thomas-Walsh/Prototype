param([switch]$DemoApprovals)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv-v17\Scripts\python.exe')) { py -3.12 -m venv .venv-v17; if ($LASTEXITCODE) { throw 'Python 3.12 environment creation failed' } }
& .\.venv-v17\Scripts\python.exe -m pip install -r requirements-v17.txt
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
if ($DemoApprovals) { $env:FUSION_LOCAL_REVIEW = '1' }
Push-Location workbench
npm ci
if ($LASTEXITCODE) { throw 'Frontend dependency installation failed' }
Pop-Location
Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$PSScriptRoot'; & '.\.venv-v17\Scripts\python.exe' -m uvicorn backend.decision_app:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList '-NoExit','-Command',"Set-Location '$PSScriptRoot\workbench'; npm run dev"
Write-Host 'Open http://127.0.0.1:5173 when both services are ready.'
