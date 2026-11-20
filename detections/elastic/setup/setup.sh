#!/bin/bash
# Runs once inside the "setup" container (see docker-compose.yml).
set -euo pipefail
cd /usr/share/elasticsearch
for v in ELASTIC_PASSWORD KIBANA_PASSWORD FILEBEAT_PASSWORD; do
  [ -n "${!v:-}" ] || { echo "Set $v in ~/jml-secrets/elastic.env"; exit 1; }
done
if [ ! -f config/certs/ca.zip ]; then
  echo "Creating CA"
  bin/elasticsearch-certutil ca --silent --pem -out config/certs/ca.zip
  unzip -q config/certs/ca.zip -d config/certs
fi
if [ ! -f config/certs/certs.zip ]; then
  echo "Creating certificates"
  printf 'instances:\n  - name: es01\n    dns: [es01, localhost]\n    ip: [127.0.0.1]\n' > config/certs/instances.yml
  bin/elasticsearch-certutil cert --silent --pem -out config/certs/certs.zip --in config/certs/instances.yml \
    --ca-cert config/certs/ca/ca.crt --ca-key config/certs/ca/ca.key
  unzip -q config/certs/certs.zip -d config/certs
fi
chown -R root:root config/certs
find config/certs -type d -exec chmod 750 {} \;
find config/certs -type f -exec chmod 640 {} \;

ES=https://es01:9200
CA=config/certs/ca/ca.crt
echo "Waiting for Elasticsearch"
until curl -s --cacert "$CA" "$ES" | grep -q "missing authentication credentials"; do sleep 5; done
api() { curl -fsS --cacert "$CA" -u "elastic:${ELASTIC_PASSWORD}" -H "Content-Type: application/json" "$@"; }

echo "Setting kibana_system password"
until api -X POST "$ES/_security/user/kibana_system/_password" -d "{\"password\":\"${KIBANA_PASSWORD}\"}" >/dev/null; do sleep 5; done

echo "Creating the Filebeat writer (can only add documents to lumen-logs-*)"
api -X PUT "$ES/_security/role/lumen_log_writer" -d '{"cluster":["monitor"],
  "indices":[{"names":["lumen-logs-*"],"privileges":["create_doc","create_index","auto_configure","view_index_metadata"]}]}' >/dev/null
api -X PUT "$ES/_security/user/lumen_filebeat" -d "{\"password\":\"${FILEBEAT_PASSWORD}\",
  \"roles\":[\"lumen_log_writer\"],\"full_name\":\"Filebeat log shipper\"}" >/dev/null

echo "Index template for lumen-logs-*"
api -X PUT "$ES/_index_template/lumen-logs" -d @/setup/index-template.json >/dev/null
echo "All done!"
