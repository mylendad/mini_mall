#!/bin/bash
# Создание изолированной БД инвентаря (запускается при первой инициализации
# тома PostgreSQL docker-entrypoint-initdb.d).
set -euo pipefail

EXISTS=$(psql -U postgres -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='mini_mall_inventory'")
if [ "$EXISTS" != "1" ]; then
    psql -U postgres -d postgres -c "CREATE DATABASE mini_mall_inventory"
fi
