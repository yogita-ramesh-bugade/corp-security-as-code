# Lumen AI - Chrome policy for Windows. Generated from browser/policy.yaml; do not edit by hand.
$ErrorActionPreference = 'Stop'
$base = 'HKLM:\SOFTWARE\Policies\Google\Chrome'
New-Item -Path $base -Force | Out-Null
Remove-Item -Path "$base\ExtensionInstallAllowlist" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -Path "$base\ExtensionInstallAllowlist" -Force | Out-Null
New-ItemProperty -Path "$base\ExtensionInstallAllowlist" -Name '1' -Value 'ghbmnnjooekpmoecnnnilnnbdlolhkhi' -PropertyType String -Force | Out-Null
Remove-Item -Path "$base\ExtensionInstallBlocklist" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -Path "$base\ExtensionInstallBlocklist" -Force | Out-Null
New-ItemProperty -Path "$base\ExtensionInstallBlocklist" -Name '1' -Value '*' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $base -Name 'PasswordManagerEnabled' -Value 0 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $base -Name 'SafeBrowsingProtectionLevel' -Value 2 -PropertyType DWord -Force | Out-Null
Write-Output 'Chrome policy applied. Check chrome://policy'
