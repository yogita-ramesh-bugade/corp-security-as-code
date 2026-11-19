# Build from jml/ (the engine needs roles.yaml, rules.py and hr/signing.py too):
#   docker compose build engine
FROM python:3.12-slim
WORKDIR /engine
COPY engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY roles.yaml rules.py hr/signing.py engine/app.py engine/core.py engine/connectors.py engine/non_hr_accounts.yaml ./
ENV ROLES_FILE=/engine/roles.yaml NON_HR_ACCOUNTS=/engine/non_hr_accounts.yaml
RUN useradd --system jml && mkdir /data && chown jml /data
USER jml
EXPOSE 8110
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8110", "--no-access-log"]
