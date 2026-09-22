param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('r1-core-down', 'r2-edge-down', 'r3-bng-down')]
    [string]$Scenario,
    [ValidateSet('Inject', 'Recover')]
    [string]$Mode = 'Inject',
    [string]$Gns3Url = 'http://localhost:3081',
    [string]$ProjectName = 'Autonomous-NOC-GNS3'
)

$ErrorActionPreference = 'Stop'
$scenarios = @{
    'r1-core-down' = @{
        Node = 'R1-CORE'
        Impact = 'Core erisimi kesilir. VPCS, R3 ve R2 yerel erisimi devam edebilir; 10.0.0.1 erisimi kesilir.'
    }
    'r2-edge-down' = @{
        Node = 'R2-EDGE'
        Impact = 'BNG ile Core arasindaki yol kesilir. Musteri R3 gatewayine ulasabilir ancak upstream erisimi kaybolur.'
    }
    'r3-bng-down' = @{
        Node = 'R3-BNG'
        Impact = 'VLAN100 istemcisinin varsayilan gecidi kaybolur ve tum upstream erisimi kesilir.'
    }
}

$selected = $scenarios[$Scenario]
$projects = Invoke-RestMethod -Uri "$Gns3Url/v2/projects"
$project = $projects | Where-Object { $_.name -eq $ProjectName } | Select-Object -First 1
if (-not $project) { throw "GNS3 projesi bulunamadi: $ProjectName" }

$nodes = Invoke-RestMethod -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes"
$node = $nodes | Where-Object { $_.name -eq $selected.Node } | Select-Object -First 1
if (-not $node) { throw "GNS3 dugumu bulunamadi: $($selected.Node)" }

Write-Host ''
Write-Host "Senaryo : $Scenario" -ForegroundColor Cyan
Write-Host "Mod     : $Mode"
Write-Host "Hedef   : $($node.name)"
Write-Host "Durum   : $($node.status)"
Write-Host "Etki    : $($selected.Impact)" -ForegroundColor Yellow
Write-Host 'Sinirlar : Yalnizca dugum stop/start API cagrisi yapilir; konfigurasyon degistirilmez.'
Write-Host ''

if ($Mode -eq 'Inject') {
    if ($node.status -ne 'started') {
        Write-Host 'Dugum zaten durmus; yeni bir degisiklik yapilmadi.' -ForegroundColor Yellow
        exit 0
    }
    $confirmation = Read-Host 'Kontrollu arizayi baslatmak icin ARIZA yazin'
    if ($confirmation.Trim().ToUpperInvariant() -ne 'ARIZA') {
        Write-Host 'Ariza testi iptal edildi; degisiklik yapilmadi.' -ForegroundColor Yellow
        exit 0
    }
    $endpoint = 'stop'
    $expected = 'stopped'
} else {
    if ($node.status -eq 'started') {
        Write-Host 'Dugum zaten calisiyor; kurtarma gerekmiyor.' -ForegroundColor Green
        exit 0
    }
    $confirmation = Read-Host 'Dugumu geri baslatmak icin E yazin'
    if ($confirmation.Trim().ToUpperInvariant() -ne 'E') {
        Write-Host 'Kurtarma iptal edildi; degisiklik yapilmadi.' -ForegroundColor Yellow
        exit 0
    }
    $endpoint = 'start'
    $expected = 'started'
}

Invoke-RestMethod -Method Post -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes/$($node.node_id)/$endpoint" | Out-Null
for ($attempt = 1; $attempt -le 10; $attempt++) {
    Start-Sleep -Seconds 1
    $current = Invoke-RestMethod -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes/$($node.node_id)"
    if ($current.status -eq $expected) {
        Write-Host "Senaryo islemi basarili: $($node.name) status=$expected" -ForegroundColor Green
        exit 0
    }
}

throw "GNS3 durum degisikligi dogrulanamadi: beklenen=$expected"
