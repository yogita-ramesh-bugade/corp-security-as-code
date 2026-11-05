# Lumen AI - Windows firewall on for all profiles, SMBv1 off
Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True
Set-SmbServerConfiguration -EnableSMB1Protocol $false -Force
Disable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -NoRestart -ErrorAction SilentlyContinue | Out-Null

Get-NetFirewallProfile | Select-Object Name, Enabled | Format-Table
Get-SmbServerConfiguration | Select-Object EnableSMB1Protocol | Format-List
