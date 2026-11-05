# Lumen AI - Defender attack surface reduction rules in AUDIT mode (log only)
# GUIDs from Microsoft's ASR rules reference
$rules = @(
  "9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2",  # Block credential stealing from LSASS
  "d4f940ab-401b-4efc-aadc-ad5f3c50688a",  # Block all Office apps from creating child processes
  "3b576869-a4ec-4529-8536-b80a7769e899",  # Block Office apps from creating executable content
  "75668c1f-73b5-4cf0-bb93-3ecf5cb7cc84"   # Block Office apps from injecting code into other processes
)
foreach ($id in $rules) {
  Add-MpPreference -AttackSurfaceReductionRules_Ids $id -AttackSurfaceReductionRules_Actions AuditMode
}

$p = Get-MpPreference
for ($i = 0; $i -lt $p.AttackSurfaceReductionRules_Ids.Count; $i++) {
  "{0}  action={1}" -f $p.AttackSurfaceReductionRules_Ids[$i], $p.AttackSurfaceReductionRules_Actions[$i]
}
