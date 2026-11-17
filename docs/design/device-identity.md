# Design: Device Identity Certificates

Project 2, Step 2.2. Status: lab implemented; production design proposed.

## Why

A password (plus MFA) proves **who** is signing in. It says nothing about **which computer** they're using. Attacker story S2 (stolen session cookie replayed from another computer) and the "personal computers hold work sessions" finding in the threat model both come down to this: the company can't tell a managed laptop from any other machine.

A device certificate gives each managed laptop its own identity. Pomerium (Step 2.3) asks the browser for it during the TLS handshake (mutual TLS), and the posture gate (Step 2.4) uses the certificate's subject, the device serial, to look up that exact laptop's health in Fleet.

**User + device + healthy device = access.** Missing any of the three means no access, or a reduced level of access.

## Lab design (what is built)

```
Admin Mac                                         Each VM (via Fleet)
---------                                         -------------------
step-ca (Lumen AI Lab CA, :9000)
mint_and_run.py
  1. fleetctl get hosts -> serial per host
  2. step ca token <serial>  ---- one-time token, 5 min, valid for ONE serial ----+
  3. writes out/<host>-enroll.(sh|ps1)                                             |
  4. fleetctl run-script --host <uuid>  ----------------------------------------> 5. generate key pair ON the device
                                                                                  6. CSR with CN = SAN = serial
step-ca  <------------------------ POST /1.0/sign {csr, ott} -------------------- 7. send CSR + token
  checks: token signature, not expired, not used before,
          CSR CN/SANs == the serial the token was made for
         --------------------------- certificate (30 days) ---------------------> 8. install in the OS store
```

| Piece | Where | In Git? |
| --- | --- | --- |
| Root CA certificate | `access-gate/device-certs/ca/root_ca.crt` | **Yes** (public) |
| Root and intermediate private keys | `~/.step/secrets/` on the admin Mac | **Never** |
| CA key password, provisioner password | `~/access-gate-secrets/` | **Never** |
| Enrollment templates and minting script | `access-gate/device-certs/` | Yes |
| Generated per-device scripts (contain tokens) | `access-gate/device-certs/out/` | **Never** (gitignored, deleted after run) |
| Device private key | On the device only | Never leaves the device |

### Where the certificate lands

| OS | Store | Key protection in the lab |
| --- | --- | --- |
| macOS | System keychain, identity "Lumen Device \<serial\>" | Imported with `-x` (not extractable through Keychain); software key |
| Windows | `Cert:\LocalMachine\My` | Created by Windows' software key provider, `Exportable = FALSE`; never a file |
| Linux | `/etc/lumen/device/device.key` (mode 600) | Plain file, root-only |

Windows uses the machine store rather than the user store, because Fleet runs scripts as SYSTEM. A user-store certificate would need a script running as the signed-in user, which is a production MDM feature (a user-scoped SCEP or ACME payload).

### Controls the lab already enforces (tested)

- **Token bound to one serial.** A token minted for serial A, used with a request for serial B, is refused: `403 ... certificate request does not contain the valid common name - got SERIAL-B, want [SERIAL-A]`.
- **Token works only once.** Replaying a used token returns `401`.
- **Short-lived tokens** (5 minutes) and **30-day certificates** (`x509-default-dur 720h`), so a lost certificate stops working on its own.
- **Private keys are generated on the device.** The CA never sees them.

## The lab's weakness: the key can be copied

Every lab key is a **software key**. Anyone with admin or root on the laptop, or malware running as root, can copy it, and then any computer can present the laptop's identity:

- **Linux:** `scp /etc/lumen/device/device.{key,crt}` to another VM. It works there.
- **macOS and Windows:** "not exportable" only blocks the normal export button and APIs. The key bytes still sit in software, so admin-level tools can extract them.

So in the lab, the certificate proves "this certificate was issued to serial X." It does **not** prove "this request comes from serial X." An attacker who steals both the session cookie (S2) **and** the device key gets past the device check.

## Production design: hardware-bound keys with attestation

The fix is to make the key **impossible to copy**: generate it inside secure hardware, and have the hardware **prove** that to the CA.

### Apple: Managed Device Attestation with ACME `device-attest-01`

1. The MDM sends an **ACME certificate payload** (`com.apple.security.acme`) with `HardwareBound = true` and `Attest = true`, pointing at step-ca's ACME provisioner.
2. The Mac creates the key pair **inside the Secure Enclave**. The private key can't leave the chip, even for root.
3. step-ca issues a `device-attest-01` challenge. The device answers with an **attestation signed by Apple**, which states the device's serial number and UDID and binds them to that key.
4. step-ca verifies the attestation chains to **Apple's Enterprise Attestation Root CA**, checks the serial against the device inventory (only company-owned serials are allowed), and issues the certificate.

The result: the certificate can only ever be used on the physical Mac whose serial is in it. Copying it to another machine gives the attacker a certificate **without the key**, which is useless.

Sketch of the step-ca side (to verify against step-ca docs when built):
```bash
step ca provisioner add lumen-mda --type ACME \
  --challenge device-attest-01 --attestation-format apple
```

Requirements and limits (Apple Platform Deployment guide):
- macOS 14 or later on **Apple silicon**; iOS 16 or later; iPadOS 16.1 or later.
- Serial and UDID are **not** included for User Enrollment (BYOD), so device certificates in this form are for company-owned devices.
- Apple limits fresh DeviceInformation attestations (about one per device every 7 days), and a failed attestation gives no reason. Plan for this in support runbooks.
- Needs a working MDM channel (APNs). This is why it can't be shown in this lab: the macOS VM never gets an APNs push token.

### Windows and Linux: TPM-backed keys

The same idea with a TPM: the key is created in the TPM and is non-migratable, and the TPM's endorsement key attests to it. Options: step-ca's `device-attest-01` with TPM attestation, or Microsoft Cloud PKI / SCEP via Intune with the TPM key storage provider. Linux uses `tpm2` tooling or step's TPM KMS.

### Other production changes

| Lab | Production |
| --- | --- |
| Admin laptop runs the CA | Dedicated CA host, root key offline (or in an HSM/KMS) |
| JWK one-time tokens pushed by a script | ACME `device-attest-01` from the MDM; no tokens to leak |
| 30-day certificates | Short-lived (e.g. 7 days) with automatic renewal; revoke on lost or stolen devices and on offboarding (feeds Project 3) |
| Machine store on Windows | User-scoped certificate, so access is tied to the user *and* the device |

## How this is checked

1. Each VM shows a certificate whose subject is its own serial (or Fleet UUID when the VM has no hardware serial).
2. A token for one serial can't get a certificate for another (`403`).
3. A used token can't be reused (`401`).
4. Copy demonstration: copying the Linux key and certificate to another VM works in the lab. This is the documented weakness, and the production design above is the fix.
