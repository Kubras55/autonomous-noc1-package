param(
    [string]$ProjectPath = ""
)

$ErrorActionPreference = "Stop"
if (-not $ProjectPath) {
    $ProjectPath = Split-Path -Parent $PSScriptRoot
}
Set-Location -LiteralPath $ProjectPath

Write-Host "[1/4] WSL Docker denetleniyor..." -ForegroundColor Cyan
wsl bash -lc "docker info >/dev/null 2>&1"
if ($LASTEXITCODE -ne 0) {
    throw "WSL Docker calismiyor. Once WSL'de: sudo systemctl start docker"
}

Write-Host "[2/4] Autonomous NOC servisleri baslatiliyor..." -ForegroundColor Cyan
wsl bash -lc "docker compose up -d postgres ollama backend prometheus alertmanager grafana"
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose servisleri baslatilamadi. WSL'de docker compose logs backend komutunu kontrol edin."
}

Write-Host "[3/4] Backend bekleniyor..." -ForegroundColor Cyan
$backendReady = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:8001/health" -TimeoutSec 3
        if ($health.status -eq "ok") {
            $backendReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $backendReady) {
    throw "Backend 60 saniye icinde hazir olmadi. WSL'de docker compose logs --tail=100 backend calistirin."
}

Write-Host "[4/4] Operator konsolu denetleniyor..." -ForegroundColor Cyan
$consoleOpen = Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue
if ($consoleOpen) {
    $consoleOpen | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

if (-not (Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue)) {
    $pythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonPath)) {
        throw "Python sanal ortami bulunamadi: $pythonPath"
    }
    $env:BACKEND_URL = "http://127.0.0.1:8001"
    $env:GNS3_URL = "http://127.0.0.1:3081"
    $env:GNS3_PROJECT = "Autonomous-NOC-Redundant-OSPF"
    Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("-m", "uvicorn", "app.operator_console:app", "--host", "0.0.0.0", "--port", "8002") `
        -WorkingDirectory $ProjectPath `
        -WindowStyle Hidden
    Start-Sleep -Seconds 4
}

$checks = @(
    @{ Name = "Backend"; Url = "http://127.0.0.1:8001/health" },
    @{ Name = "Operator konsolu"; Url = "http://127.0.0.1:8002" },
    @{ Name = "Grafana"; Url = "http://127.0.0.1:3001/api/health" },
    @{ Name = "Prometheus"; Url = "http://127.0.0.1:9090/-/ready" },
    @{ Name = "Alertmanager"; Url = "http://127.0.0.1:9093/-/ready" },
    @{ Name = "Ollama"; Url = "http://127.0.0.1:11434/api/tags" }
)

Write-Host ""
foreach ($check in $checks) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $check.Url -TimeoutSec 8 | Out-Null
        Write-Host "[OK] $($check.Name)" -ForegroundColor Green
    } catch {
        Write-Host "[UYARI] $($check.Name): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "GNS3 projesini acin ve tum dugumleri baslatin: Autonomous-NOC-Redundant-OSPF" -ForegroundColor Cyan
Write-Host "Operator konsolu: http://localhost:8002"
Write-Host "Grafana:          http://localhost:3001"
Write-Host "Backend:          http://localhost:8001/health"
