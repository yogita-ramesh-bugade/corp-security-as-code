#!/bin/bash
# Lumen AI device certificate enrollment: macOS.
# This is a TEMPLATE. mint_and_run.py fills in the placeholders (serial, token, CA URL, root cert)
# and writes a per-device copy into out/ (gitignored, because it contains a one-time token).
# Runs as root via Fleet. The private key is generated ON the device, imported into the
# System keychain as NON-EXTRACTABLE (-x), and the key file is deleted.
set -euo pipefail

SERIAL='__SERIAL__'
TOKEN='__TOKEN__'
CA_URL='__CA_URL__'
DIR=/Library/Lumen/device
KEYCHAIN=/Library/Keychains/System.keychain
OPENSSL=/usr/bin/openssl   # Apple's LibreSSL: its .p12 files import cleanly into Keychain

mkdir -p "$DIR"
cat > "$DIR/root_ca.crt" <<'EOF'
__ROOT_PEM__
EOF

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/req.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
req_extensions = ext
[dn]
CN = $SERIAL
[ext]
subjectAltName = DNS:$SERIAL
EOF

# 1. Key pair, made here on the device
"$OPENSSL" ecparam -name prime256v1 -genkey -noout -out "$WORK/device.key"

# 2. Certificate request: subject = this device's serial
"$OPENSSL" req -new -key "$WORK/device.key" -config "$WORK/req.cnf" -out "$WORK/device.csr"

# 3. Send request + one-time token to step-ca
CSR=$(awk '{printf "%s\\n", $0}' "$WORK/device.csr")
printf '{"csr":"%s","ott":"%s"}' "$CSR" "$TOKEN" > "$WORK/req.json"
curl -sS --fail-with-body --cacert "$DIR/root_ca.crt" \
  -H 'Content-Type: application/json' --data @"$WORK/req.json" \
  "$CA_URL/1.0/sign" -o "$WORK/resp.json"

# 4. Pull the certificate and intermediate out of the JSON (plutil reads JSON)
plutil -extract crt raw -o "$WORK/device.crt" "$WORK/resp.json"
plutil -extract ca raw -o "$WORK/ca.crt" "$WORK/resp.json"
cp "$WORK/device.crt" "$DIR/device.crt"

# 5. Remove any older Lumen identity for this serial, then import the new one
security delete-certificate -c "$SERIAL" "$KEYCHAIN" >/dev/null 2>&1 || true
P12PASS=$(uuidgen)
"$OPENSSL" pkcs12 -export -inkey "$WORK/device.key" -in "$WORK/device.crt" \
  -certfile "$WORK/ca.crt" -name "Lumen Device $SERIAL" \
  -out "$WORK/device.p12" -passout pass:"$P12PASS"
ALLOW=(-T /usr/bin/security)
[ -d "/Applications/Google Chrome.app" ] && ALLOW+=(-T "/Applications/Google Chrome.app")
security import "$WORK/device.p12" -k "$KEYCHAIN" -f pkcs12 -P "$P12PASS" -x "${ALLOW[@]}"

echo "Installed device certificate in System keychain:"
security find-certificate -c "$SERIAL" -p "$KEYCHAIN" | "$OPENSSL" x509 -noout -subject -issuer -enddate
