# Lumen AI device certificate enrollment: Windows.
# This is a TEMPLATE. mint_and_run.py fills in the placeholders (serial, token, CA URL, root cert)
# and writes a per-device copy into out/ (gitignored, because it contains a one-time token).
# Fleet runs scripts as SYSTEM, so the certificate goes into the MACHINE store
# (Cert:\LocalMachine\My). The private key is created by Windows itself and marked
# non-exportable; it never exists as a file.
$ErrorActionPreference = 'Stop'

$Serial = '__SERIAL__'
$Token  = '__TOKEN__'
$CaUrl  = '__CA_URL__'
$Dir    = 'C:\ProgramData\Lumen\device'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

$RootPem = @'
__ROOT_PEM__
'@
Set-Content -Path "$Dir\root_ca.crt" -Value $RootPem -Encoding ascii
# Trust the Lumen lab root so Windows can reach the CA over HTTPS and build the chain
Import-Certificate -FilePath "$Dir\root_ca.crt" -CertStoreLocation Cert:\LocalMachine\Root | Out-Null

# 1 + 2. Key pair (inside Windows, non-exportable) and certificate request
$inf = @"
[Version]
Signature = "`$Windows NT`$"

[NewRequest]
Subject = "CN=$Serial"
KeyAlgorithm = RSA
KeyLength = 2048
HashAlgorithm = sha256
MachineKeySet = TRUE
Exportable = FALSE
ProviderName = "Microsoft Software Key Storage Provider"
RequestType = PKCS10

[Extensions]
2.5.29.17 = "{text}"
_continue_ = "dns=$Serial&"
"@
Set-Content -Path "$Dir\req.inf" -Value $inf -Encoding ascii
Remove-Item "$Dir\req.csr" -ErrorAction SilentlyContinue
certreq.exe -new -q -machine "$Dir\req.inf" "$Dir\req.csr" | Out-Null
if (-not (Test-Path "$Dir\req.csr")) { throw "certreq did not create a request" }
$csr = (Get-Content "$Dir\req.csr" -Raw) -replace 'NEW CERTIFICATE REQUEST', 'CERTIFICATE REQUEST'

# 3. Send request + one-time token to step-ca
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$body = @{ csr = $csr; ott = $Token } | ConvertTo-Json
$resp = Invoke-RestMethod -Method Post -Uri "$CaUrl/1.0/sign" -ContentType 'application/json' -Body $body

# 4. Install intermediate, then pair the certificate with its waiting private key
Set-Content -Path "$Dir\intermediate.crt" -Value $resp.ca -Encoding ascii
Import-Certificate -FilePath "$Dir\intermediate.crt" -CertStoreLocation Cert:\LocalMachine\CA | Out-Null
Set-Content -Path "$Dir\device.crt" -Value $resp.crt -Encoding ascii
certreq.exe -accept -q -machine "$Dir\device.crt" | Out-Null
Remove-Item "$Dir\req.inf", "$Dir\req.csr" -ErrorAction SilentlyContinue

Write-Output "Installed device certificate in LocalMachine\My:"
Get-ChildItem Cert:\LocalMachine\My |
  Where-Object { $_.Subject -eq "CN=$Serial" } |
  Select-Object Subject, Issuer, NotAfter, HasPrivateKey, Thumbprint | Format-List | Out-String
