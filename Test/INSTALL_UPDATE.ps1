param([string]$ProjectPath = 'D:\Fusion_Prototype\fusion_bim_platform')
$ErrorActionPreference='Stop'
$source=Join-Path $PSScriptRoot 'fusion_bim_platform'
if (!(Test-Path $source)) { throw "Update payload missing: $source" }
if (!(Test-Path $ProjectPath)) { throw "Existing full Fusion project not found: $ProjectPath. This v0.17 ZIP is an overlay, not a standalone complete application." }
$required=@('frontend\package.json','frontend\src\Viewer.tsx','frontend\src\MeshViewer.tsx','frontend\src\DigitalThread.tsx','frontend\src\ModelQA.tsx','frontend\src\ImpactPanel.tsx','frontend\src\types.ts','backend\graph_cpm.py','backend\coordination_intelligence.py','backend\coordination_actions.py','backend\spatial_intelligence.py','data\elements.json')
$missing=@($required | Where-Object { !(Test-Path (Join-Path $ProjectPath $_)) })
if ($missing.Count -gt 0) { throw "Existing installation lacks required full-platform files: $($missing -join ', '). No files were changed. Supply a complete earlier Fusion project first." }
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$backup=Join-Path $ProjectPath ("backups\before_v17_"+$stamp)
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$changes=@('backend\app.py','backend\decision_ledger.py','backend\knowledge_graph.py','backend\circulation.py','backend\demo_network.py','frontend\src\App.tsx','frontend\src\DecisionLedger.tsx','frontend\src\IntelligenceWorkspaces.tsx','frontend\src\style.css','requirements-v17.txt','compose.graph.yml','examples\spatial_demo.json')
foreach ($name in $changes) {
 $dest=Join-Path $ProjectPath $name
 $origin=Join-Path $source $name
 if (!(Test-Path $origin)) { continue }
 if (Test-Path $dest) {
  $saved=Join-Path $backup $name
  New-Item -ItemType Directory -Force -Path (Split-Path $saved -Parent) | Out-Null
  Copy-Item -LiteralPath $dest -Destination $saved -Force
 }
}
foreach ($name in $changes) {
 $origin=Join-Path $source $name
 if (!(Test-Path $origin)) { continue }
 $dest=Join-Path $ProjectPath $name
 New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
 Copy-Item -LiteralPath $origin -Destination $dest -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LAUNCH_FUSION.ps1') -Destination (Join-Path $ProjectPath 'LAUNCH_FUSION.ps1') -Force
Write-Host "Updated project: $ProjectPath" -ForegroundColor Green
Write-Host "Replaced files were backed up to: $backup"
Write-Host 'Original models, GLBs, data, databases, and other modules were preserved.'
Write-Host 'Next: Run LAUNCH_FUSION.ps1 from your existing project folder.'
