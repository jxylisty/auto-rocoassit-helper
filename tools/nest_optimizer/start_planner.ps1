$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$page = Join-Path $root "docs\roco_shiny_breeding_planner.html"

function Test-SolverHealth {
  try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -Method Get -TimeoutSec 2
    return $response.ok -eq $true
  } catch {
    return $false
  }
}

if (-not (Test-SolverHealth)) {
  Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "tools.nest_optimizer.app:app", "--host", "127.0.0.1", "--port", "8765" -WorkingDirectory $root | Out-Null
  Start-Sleep -Seconds 2
}

Start-Process -FilePath $page | Out-Null
