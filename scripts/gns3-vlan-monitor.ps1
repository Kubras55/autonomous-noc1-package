param(
    [string]$ProjectName = 'Autonomous-NOC-GNS3-VLAN200',
    [string]$Gns3Url = 'http://localhost:3081',
    [string]$BackendUrl = 'http://localhost:8001',
    [int]$IntervalSeconds = 5,
    [int]$FailureThreshold = 2,
    [switch]$NoAuth
)

$ErrorActionPreference = 'Stop'
$headers = @{}
if (-not $NoAuth) {
    $credential = Get-Credential -Message 'GNS3 API kullanici adi ve parolasi'
    $plainPassword = $credential.GetNetworkCredential().Password
    $tokenBytes = [Text.Encoding]::ASCII.GetBytes("$($credential.UserName):$plainPassword")
    $headers.Authorization = "Basic $([Convert]::ToBase64String($tokenBytes))"
}

$checks = @(
    @{ Node = 'VPCS-VLAN100'; Vlan = '100'; Gateway = '192.168.100.1'; Core = '10.0.0.1'; Service = 'subscriber-vlan-100' },
    @{ Node = 'VPCS-VLAN200'; Vlan = '200'; Gateway = '192.168.200.1'; Core = '10.0.0.1'; Service = 'subscriber-vlan-200' }
)

$failures = @{}
$firing = @{}
$issueKinds = @{}
foreach ($check in $checks) {
    $failures[$check.Service] = 0
    $firing[$check.Service] = $false
    $issueKinds[$check.Service] = 'none'
}

function Invoke-VpcsCommand {
    param(
        [string]$HostName,
        [int]$Port,
        [string]$Command,
        [int]$WaitMilliseconds = 4500
    )

    $client = [Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync($HostName, $Port)
        if (-not $connect.Wait(3000)) {
            throw "Console connection timed out: ${HostName}:$Port"
        }

        $stream = $client.GetStream()
        $stream.ReadTimeout = 1000
        $stream.WriteTimeout = 1000

        Start-Sleep -Milliseconds 250
        while ($stream.DataAvailable) {
            $discard = New-Object byte[] 4096
            [void]$stream.Read($discard, 0, $discard.Length)
        }

        $bytes = [Text.Encoding]::ASCII.GetBytes("$Command`r`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        Start-Sleep -Milliseconds $WaitMilliseconds

        $result = New-Object Text.StringBuilder
        $buffer = New-Object byte[] 4096
        while ($stream.DataAvailable) {
            $count = $stream.Read($buffer, 0, $buffer.Length)
            if ($count -le 0) { break }
            [void]$result.Append([Text.Encoding]::ASCII.GetString($buffer, 0, $count))
            Start-Sleep -Milliseconds 100
        }
        return $result.ToString()
    }
    finally {
        $client.Dispose()
    }
}

function Send-VlanAlert {
    param(
        [hashtable]$Check,
        [ValidateSet('firing', 'resolved')]
        [string]$Status,
        [ValidateSet('gateway', 'upstream')]
        [string]$IssueKind
    )

    $isGateway = $IssueKind -eq 'gateway'
    $alertName = if ($isGateway) { 'GNS3VlanGatewayUnreachable' } else { 'GNS3VlanUpstreamUnreachable' }
    $summary = if ($isGateway) {
        "VLAN $($Check.Vlan) gateway is unreachable"
    } else {
        "VLAN $($Check.Vlan) gateway is reachable but core path is unreachable"
    }
    $description = if ($isGateway) {
        "$($Check.Node) cannot reach gateway $($Check.Gateway). Check the access VLAN, 802.1Q sub-interface and gateway state on R3-BNG."
    } else {
        "$($Check.Node) reaches gateway $($Check.Gateway) but cannot reach core $($Check.Core). Check R3/R2 forwarding and the static return routes for VLAN $($Check.Vlan)."
    }

    $payload = @{
        alerts = @(@{
            status = $Status
            labels = @{
                alertname = $alertName
                severity = 'high'
                service = $Check.Service
                source = 'gns3-vlan-monitor'
                vlan = $Check.Vlan
                node = $Check.Node
            }
            annotations = @{
                summary = $summary
                description = $description
            }
            fingerprint = "gns3-vlan-health:$ProjectName`:$($Check.Vlan)"
        })
    } | ConvertTo-Json -Depth 7

    $body = [Text.Encoding]::UTF8.GetBytes($payload)
    Invoke-RestMethod -Method Post -Uri "$BackendUrl/alerts/prometheus" `
        -ContentType 'application/json; charset=utf-8' -Body $body | Out-Null
}

Write-Host "VLAN monitor started: project=$ProjectName interval=${IntervalSeconds}s threshold=$FailureThreshold"

while ($true) {
    try {
        $projects = Invoke-RestMethod -Uri "$Gns3Url/v2/projects" -Headers $headers
        $project = $projects | Where-Object { $_.name -eq $ProjectName } | Select-Object -First 1
        if (-not $project) { throw "GNS3 project not found: $ProjectName" }

        $nodes = Invoke-RestMethod -Uri "$Gns3Url/v2/projects/$($project.project_id)/nodes" -Headers $headers

        foreach ($check in $checks) {
            $node = $nodes | Where-Object { $_.name -eq $check.Node } | Select-Object -First 1
            $healthy = $false
            $detail = 'node not found'

            if ($node -and $node.status -eq 'started' -and $node.console) {
                try {
                    $consoleHost = if ($node.console_host) { $node.console_host } else { '127.0.0.1' }
                    $gatewayOutput = Invoke-VpcsCommand -HostName $consoleHost -Port $node.console `
                        -Command "ping $($check.Gateway) -c 2"
                    $gatewayHealthy = $gatewayOutput -match '(?i)bytes from'
                    if ($gatewayHealthy) {
                        $coreOutput = Invoke-VpcsCommand -HostName $consoleHost -Port $node.console `
                            -Command "ping $($check.Core) -c 2"
                        $coreHealthy = $coreOutput -match '(?i)bytes from'
                        $healthy = $coreHealthy
                        $issueKind = if ($coreHealthy) { 'none' } else { 'upstream' }
                        $detail = if ($coreHealthy) { 'gateway and core replied' } else { 'gateway replied but core had no reply' }
                    }
                    else {
                        $healthy = $false
                        $issueKind = 'gateway'
                        $detail = 'gateway ping had no reply'
                    }
                }
                catch {
                    $issueKind = 'gateway'
                    $detail = $_.Exception.Message
                }
            }
            elseif ($node) {
                $issueKind = 'gateway'
                $detail = "node status=$($node.status) console=$($node.console)"
            }
            else {
                $issueKind = 'gateway'
            }

            $service = $check.Service
            $failures[$service] = if ($healthy) { 0 } else { $failures[$service] + 1 }

            if ($failures[$service] -ge $FailureThreshold -and -not $firing[$service]) {
                $issueKinds[$service] = $issueKind
                Send-VlanAlert -Check $check -Status 'firing' -IssueKind $issueKind
                $firing[$service] = $true
                Write-Host "ALERT firing: $service issue=$issueKind detail=$detail" -ForegroundColor Red
            }
            elseif ($healthy -and $firing[$service]) {
                Send-VlanAlert -Check $check -Status 'resolved' -IssueKind $issueKinds[$service]
                $firing[$service] = $false
                $issueKinds[$service] = 'none'
                Write-Host "ALERT resolved: $service gateway=$($check.Gateway) core=$($check.Core)" -ForegroundColor Green
            }
            else {
                $color = if ($healthy) { 'DarkGreen' } else { 'DarkYellow' }
                Write-Host "CHECK $service healthy=$healthy failures=$($failures[$service]) detail=$detail" -ForegroundColor $color
            }
        }
    }
    catch {
        Write-Warning "VLAN monitor cycle failed: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds $IntervalSeconds
}
