param([switch]$DemoApprovals, [switch]$SkipInstall)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
Set-Location $root
$required=@('backend\app.py','frontend\package.json','frontend\src\Viewer.tsx','frontend\src\MeshViewer.tsx','backend\graph_cpm.py','data\elements.json')
$missing=@($required | Where-Object { !(Test-Path (Join-Path $root $_)) })
if ($missing.Count -gt 0) { throw "Cannot launch complete Fusion platform; missing: $($missing -join ', ')" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js/npm not found. Install Node.js 20 or newer.' }
$py=Join-Path $root '.venv-v17\Scripts\python.exe'
if (!(Test-Path $py)) {
 if (!(Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python launcher not found. Install Python 3.12.' }
 & py -3.12 -m venv '.venv-v17'
 if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python 3.12 virtual environment.' }
}
if (!$SkipInstall) {
 & $py -m pip install -r 'requirements-v17.txt'
 if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
 Push-Location frontend
 try {
  if (Test-Path 'package-lock.json') { & npm ci } else { & npm install }
  if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed.' }
  & npm run build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed. Check dependencies and source compatibility before launching.' }
 } finally { Pop-Location }
}
$occupied=@(8000,5173 | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
if ($occupied.Count -gt 0) { throw 'Port 8000 or 5173 is already in use. Close the old Fusion backend/frontend terminals first.' }
$env:FUSION_LOCAL_REVIEW=if($DemoApprovals){'1'}else{'0'}
$backendCmd="Set-Location -LiteralPath '$($root.Replace("'","''"))'; & '$($py.Replace("'","''"))' -m uvicorn backend.app:app --host 127.0.0.1 --port 8000"
$frontendDir=Join-Path $root 'frontend'
$frontendCmd="Set-Location -LiteralPath '$($frontendDir.Replace("'","''"))'; npm run dev -- --host 127.0.0.1 --port 5173"
Start-Process powershell.exe -ArgumentList @('-NoExit','-Command',$backendCmd) -WorkingDirectory $root | Out-Null
Start-Process powershell.exe -ArgumentList @('-NoExit','-Command',$frontendCmd) -WorkingDirectory $frontendDir | Out-Null
Write-Host 'Starting the FULL Fusion dashboard: model, coordination, programme, QA, graph, circulation and decision ledger.' -ForegroundColor Green
$ready=$false
for($i=0;$i -lt 40;$i++){
 try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){$ready=$true;break} } catch { Start-Sleep -Milliseconds 750 }
}
if($ready){Start-Process 'http://127.0.0.1:5173/';Write-Host 'Full dashboard opened.'}
else {Write-Warning 'Frontend did not become ready. Check the backend and frontend PowerShell windows for errors.'}
