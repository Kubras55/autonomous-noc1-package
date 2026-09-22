param(
    [string]$ProjectName = 'Autonomous-NOC-GNS3',
    [string]$Gns3Url = 'http://localhost:3081',
    [string]$BackendUrl = 'http://localhost:8000',
    [int]$IntervalSeconds = 5,
    [int]$FailureThreshold = 2,
    [switch]$NoAuth
)

$ErrorActionPreference = 'Stop'
$headers = @{}
if (-not $NoAuth) {
    $credential = Get-Credential -Message 'GNS3 API kullanici adi ve parolasi'
    $plainPassword = $credential.GetNetworkCredential().Password
    $basicToken = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($credential.UserName):$plainPassword"))
    $headers.Authorization = "Basic $basicToken"
}
$watchedNodes = @(
    'R1-CORE',
    'R2-EDGE',
    'R3-BNG',
    'VPCS-VLAN100',
    'VPCS-VLAN200'
)
$failures = @{}
$firing = @{}
foreach ($name in $watchedNodes) { $failures[$name] = 0; $firing[$name] = $false }

function Send-NocAlert([string]$Name, [string]$Status) {
    $payload = @{
        alerts = @(@{
            status = $Status
            labels = @{ alertname = 'GNS3NodeDown'; severity = 'critical'; service = $Name; source = 'gns3' }
            annotations = @{ summary = "$Name is down in GNS3"; description = "GNS3 node is stopped or unavailable. API alarm status: $Status." }
            fingerprint = "gns3-node-down:$ProjectName`:$Name"
        })
    } | ConvertTo-Json -Depth 6
    $body = [Text.Encoding]::UTF8.GetBytes($payload)
    Invoke-RestMethod -Method Post -Uri "$BackendUrl/alerts/prometheus" -ContentType 'application/json; charset=utf-8' -Body $body | Out-Null
}

Write-Host "GNS3 monitor started: project=$ProjectName interval=${IntervalSeconds}s threshold=$FailureThreshold"
while ($true) {
    try {
        $projects = Invoke-RestMethod -Uri "$Gns3Url/v2/projects" -Headers $headers
        $project = $projects | Where-Object { $_.name -eq $ProjectName } | Select-Object -First 1
        if (-not $project) { throw "GNS3 project not found: $ProjectName" }
        $nodes = Invoke-RestMethod -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes" -Headers $headers
        foreach ($name in $watchedNodes) {
            $node = $nodes | Where-Object { $_.name -eq $name } | Select-Object -First 1
            $healthy = $node -and $node.status -eq 'started'
            $failures[$name] = if ($healthy) { 0 } else { $failures[$name] + 1 }
            if ($failures[$name] -ge $FailureThreshold -and -not $firing[$name]) {
                Send-NocAlert $name 'firing'
                $firing[$name] = $true
                Write-Host "ALERT firing: $name status=$($node.status)" -ForegroundColor Red
            }
            elseif ($healthy -and $firing[$name]) {
                Send-NocAlert $name 'resolved'
                $firing[$name] = $false
                Write-Host "ALERT resolved: $name" -ForegroundColor Green
            }
        }
    }
    catch { Write-Warning "Monitor cycle failed: $($_.Exception.Message)" }
    Start-Sleep -Seconds $IntervalSeconds
}
