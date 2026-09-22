param(
    [Parameter(Mandatory = $true)]
    [string]$IncidentId,
    [string]$BackendUrl = 'http://localhost:8001',
    [string]$Gns3Url = 'http://localhost:3081',
    [string]$ProjectName = 'Autonomous-NOC-GNS3'
)

$ErrorActionPreference = 'Stop'

function Get-Utf8Json([string]$Uri) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 240
    $text = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
    return $text | ConvertFrom-Json
}

Write-Host "Incident yukleniyor: $IncidentId" -ForegroundColor Cyan
$incident = Get-Utf8Json "$BackendUrl/incidents/$IncidentId"
$analysis = Get-Utf8Json "$BackendUrl/incidents/$IncidentId/ai-analysis"

Write-Host ""
Write-Host "Servis    : $($incident.affected_service)"
Write-Host "Saglayici : $($analysis.provider)"
Write-Host "Risk      : $($analysis.risk)"
Write-Host "Guven     : $($analysis.confidence_score)"
Write-Host "Oneri     : $($analysis.recommended_action)"
Write-Host "Neden     : $($analysis.root_cause)"
Write-Host ""

$allowedAction = 'start_gns3_node_and_verify_links'
if ($analysis.recommended_action -ne $allowedAction) {
    throw "Guvenlik engeli: izin verilmeyen islem: $($analysis.recommended_action)"
}
if ($analysis.risk -eq 'HIGH') {
    throw 'Guvenlik engeli: HIGH riskli islem otomatik uygulanamaz.'
}

$projects = Invoke-RestMethod -Uri "$Gns3Url/v2/projects"
$project = $projects | Where-Object { $_.name -eq $ProjectName } | Select-Object -First 1
if (-not $project) {
    throw "GNS3 projesi bulunamadi: $ProjectName"
}

$nodes = Invoke-RestMethod -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes"
$node = $nodes | Where-Object { $_.name -eq $incident.affected_service } | Select-Object -First 1
if (-not $node) {
    throw "GNS3 dugumu bulunamadi: $($incident.affected_service)"
}

Write-Host 'PLANLANAN MUDAHALE' -ForegroundColor Magenta
Write-Host "1. Hedef GNS3 projesi : $ProjectName"
Write-Host "2. Hedef cihaz         : $($node.name)"
Write-Host "3. Mevcut cihaz durumu : $($node.status)"
if ($node.status -eq 'started') {
    Write-Host '4. Cihaz zaten calisiyor; yeniden baslatilmayacak, sadece durumu dogrulanacak.'
} else {
    Write-Host '4. Yalnizca GNS3 Start API cagrisi yapilarak cihaz baslatilacak.'
}
Write-Host '5. En fazla 20 saniye boyunca status=started sonucu kontrol edilecek.'
Write-Host '6. Router konfigurasyonu, IP, VLAN ve route ayarlari degistirilmeyecek.'
Write-Host '7. Cihaz silinmeyecek, yeniden kurulmayacak ve diger dugumlere dokunulmayacak.'
Write-Host ""

$decision = Read-Host 'Bu mudahaleyi onayliyor musunuz? (E/H)'
if ($decision.Trim().ToUpperInvariant() -ne 'E') {
    Write-Host 'Mudahale reddedildi; GNS3 uzerinde degisiklik yapilmadi.' -ForegroundColor Yellow
    exit 0
}

if ($node.status -ne 'started') {
    Write-Host "GNS3 dugumu baslatiliyor: $($node.name)" -ForegroundColor Cyan
    Invoke-RestMethod -Method Post -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes/$($node.node_id)/start" | Out-Null
} else {
    Write-Host 'Dugum zaten calisiyor; durum dogrulanacak.' -ForegroundColor Yellow
}

for ($attempt = 1; $attempt -le 10; $attempt++) {
    Start-Sleep -Seconds 2
    $current = Invoke-RestMethod -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes/$($node.node_id)"
    if ($current.status -eq 'started') {
        Write-Host "Mudahale basarili: $($node.name) status=started" -ForegroundColor Green
        exit 0
    }
}

throw "Mudahale dogrulanamadi: $($node.name) baslatilamadi."
