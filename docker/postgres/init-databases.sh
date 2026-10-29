#!/bin/bash
# Runs once, on first start. Creates one login and one database per service.
# "set -e" stops the script at the first error instead of carrying on half-finished.
set -e

# ON_ERROR_STOP makes psql fail loudly on a bad statement.
# The $...$ names below are filled in by the shell from the environment variables set in docker-compose.yml.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<EOSQL
  CREATE ROLE ledger_core LOGIN PASSWORD '$LEDGER_CORE_DB_PASSWORD';
  CREATE DATABASE ledger_core OWNER ledger_core;

  CREATE ROLE assistant LOGIN PASSWORD '$ASSISTANT_DB_PASSWORD';
  CREATE DATABASE assistant OWNER assistant;
EOSQL