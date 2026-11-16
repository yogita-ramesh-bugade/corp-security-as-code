# Lumen AI - Windows App Control (WDAC) base policy in AUDIT mode.
# Builds from Microsoft's DefaultWindows example policy, trusts reputable apps (ISG),
# and deploys without a reboot. Safe to re-run: reuses the same policy ID.
$ErrorActionPreference = 'Stop'

$dir = Join-Path $env:ProgramData 'LumenAI\wdac'
$xml = Join-Path $dir 'LumenAI-Base-Audit.xml'
New-Item -ItemType Directory -Path $dir -Force | Out-Null

if (-not (Test-Path $xml)) {
    Copy-Item "$env:windir\schemas\CodeIntegrity\ExamplePolicies\DefaultWindows_Audit.xml" $xml -Force
    Set-CIPolicyIdInfo -FilePath $xml -PolicyName 'Lumen AI Base (Audit)' -ResetPolicyID | Out-Null
}

Set-RuleOption -FilePath $xml -Option 3    # Audit mode: log (event 3076), never block
Set-RuleOption -FilePath $xml -Option 14   # Trust apps with good reputation (Intelligent Security Graph)
Set-RuleOption -FilePath $xml -Option 16   # Apply policy updates without a reboot

[xml]$policy = Get-Content $xml
$id  = $policy.SiPolicy.PolicyID
$cip = Join-Path $dir "$id.cip"
ConvertFrom-CIPolicy -XmlFilePath $xml -BinaryFilePath $cip | Out-Null

CiTool.exe --update-policy $cip
Write-Output "Deployed Lumen AI WDAC audit policy $id"
Write-Output "Policy XML: $xml"
