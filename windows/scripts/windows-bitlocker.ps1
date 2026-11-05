# Lumen AI - BitLocker on C: with TPM + recovery password
$vol = Get-BitLockerVolume -MountPoint "C:"
if ($vol.ProtectionStatus -eq "On") {
  "BitLocker already on for C:"
} else {
  if (-not ($vol.KeyProtector | Where-Object KeyProtectorType -eq "RecoveryPassword")) {
    Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector | Out-Null
  }
  Enable-BitLocker -MountPoint "C:" -TpmProtector -EncryptionMethod XtsAes256 -UsedSpaceOnly -SkipHardwareTest
}
Get-BitLockerVolume -MountPoint "C:" | Select-Object MountPoint, VolumeStatus, ProtectionStatus, EncryptionPercentage | Format-List
(Get-BitLockerVolume -MountPoint "C:").KeyProtector | Where-Object KeyProtectorType -eq "RecoveryPassword" | Select-Object RecoveryPassword
