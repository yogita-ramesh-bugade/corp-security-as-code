#!/bin/bash
# Lumen AI device certificate enrollment: Linux.
# This is a TEMPLATE. mint_and_run.py fills in the placeholders (serial, token, CA URL, root cert)
# and writes a per-device copy into out/ (gitignored, because it contains a one-time token).
# Runs as root via Fleet. The private key is generated ON the device and never leaves it.
set -euo pipefail

SERIAL='__SERIAL__'
TOKEN='__TOKEN__'
CA_URL='__CA_URL__'
DIR=/etc/lumen/device

mkdir -p "$DIR"
chmod 700 "$DIR"
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
openssl ecparam -name prime256v1 -genkey -noout -out "$WORK/device.key"

# 2. Certificate request: subject = this device's serial
openssl req -new -key "$WORK/device.key" -config "$WORK/req.cnf" -out "$WORK/device.csr"

# 3. Send request + one-time token to step-ca
CSR=$(awk '{printf "%s\\n", $0}' "$WORK/device.csr")
printf '{"csr":"%s","ott":"%s"}' "$CSR" "$TOKEN" > "$WORK/req.json"
curl -sS --fail-with-body --cacert "$DIR/root_ca.crt" \
  -H 'Content-Type: application/json' --data @"$WORK/req.json" \
  "$CA_URL/1.0/sign" -o "$WORK/resp.json"

# 4. Save certificate, chain and key (key readable by root only)
python3 - "$WORK/resp.json" "$WORK" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2] + "/device.crt", "w").write(r["crt"])
open(sys.argv[2] + "/chain.crt", "w").write(r["crt"] + r["ca"])
PY
install -m 600 "$WORK/device.key" "$DIR/device.key"
install -m 644 "$WORK/device.crt" "$DIR/device.crt"
install -m 644 "$WORK/chain.crt" "$DIR/chain.crt"

echo "Installed device certificate:"
openssl x509 -in "$DIR/device.crt" -noout -subject -issuer -enddate
