$ErrorActionPreference = 'Stop'
$health = Invoke-RestMethod http://localhost:8001/health
if ($health.status -ne 'ok') { throw 'Backend health check failed' }
$json = @{
  title='VLAN 100 access error'; description='BNG dot1q mismatch'; severity='high'; source='lab-r3'; affected_service='subscriber-vlan-100'
} | ConvertTo-Json
$body = [System.Text.Encoding]::UTF8.GetBytes($json)
$incident = Invoke-RestMethod -Method Post -Uri http://localhost:8001/incidents -ContentType 'application/json; charset=utf-8' -Body $body
Invoke-RestMethod "http://localhost:8001/incidents/$($incident.id)/ai-analysis"

