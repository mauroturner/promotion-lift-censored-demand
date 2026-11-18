#!/usr/bin/env bash
# The initialization of the Airflow services: the airflow-init service of docker-compose.yaml runs it (with its carriage returns removed) as root
# before every other service, which starts only when this script exits 0. /entrypoint migrates the metadata database and creates the admin user
# (_AIRFLOW_DB_MIGRATE and _AIRFLOW_WWW_USER_CREATE), so the script stops at its first failed command: without it a failed migration was
# followed by a chown that succeeds, and the initialization reported success (project 03, review of U23; D24).
set -euo pipefail
mkdir -v -p /opt/airflow/{logs,dags,plugins,config}
/entrypoint airflow version
/entrypoint airflow config list >/dev/null
# Only what Airflow writes: ./dags and ./plugins are mounted read-only and cannot change owner.
chown -v -R "${AIRFLOW_UID:-50000}:0" /opt/airflow/{logs,config}
