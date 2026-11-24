#!/usr/bin/env bash
#
# Stand up everything the Data page can be pointed at:
#
#   karag-test-api    a read-only demo API      http://karag-test-api:8100
#   karag-test-pg     Postgres 16               karag-test-pg:5432   / :55432 on the host
#   karag-test-mysql  MySQL 8.0                 karag-test-mysql:3306 / :53306 on the host
#
# All three join the platform's compose network, so the API container reaches
# them by name — which is what the wizard's "host" field wants. Data comes from
# testbench/build.py, so every run seeds identical rows.
#
#   ./testbench/up.sh          bring it up (idempotent: recreates the containers)
#   ./testbench/down.sh        remove it again
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

NETWORK="${KARAG_NETWORK:-ka_rag_default}"
PG_IMAGE="postgres:16-alpine"
MYSQL_IMAGE="mysql:8.0"
DB=apteka
PG_SUPER_PW=postgres
MYSQL_ROOT_PW=root

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }

step "Building fixtures"
python3 build.py

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "network $NETWORK is missing — start the platform first (docker compose up -d)" >&2
    exit 1
fi

step "Removing any previous testbench containers"
docker rm -f karag-test-api karag-test-pg karag-test-mysql >/dev/null 2>&1 || true

# --- the demo API ---------------------------------------------------------
# Runs on the platform's own image purely because it already has Python; the
# server itself is stdlib and mounted read-only from the checkout.
step "Starting karag-test-api"
docker run -d --name karag-test-api --network "$NETWORK" \
    -v "$ROOT/testbench:/testbench:ro" \
    -w /testbench -e PORT=8100 \
    -p 127.0.0.1:8100:8100 \
    --restart unless-stopped \
    karag-api python api_server.py >/dev/null

# --- Postgres -------------------------------------------------------------
step "Starting karag-test-pg"
docker run -d --name karag-test-pg --network "$NETWORK" \
    -e POSTGRES_PASSWORD="$PG_SUPER_PW" -e POSTGRES_DB="$DB" \
    -p 127.0.0.1:55432:5432 \
    --restart unless-stopped \
    "$PG_IMAGE" >/dev/null

printf '  waiting for postgres'
for _ in $(seq 1 60); do
    if docker exec karag-test-pg pg_isready -U postgres -d "$DB" >/dev/null 2>&1; then break; fi
    printf '.'; sleep 1
done; echo

docker exec -i karag-test-pg psql -v ON_ERROR_STOP=1 -U postgres -d "$DB" \
    < build/apteka_pg.sql >/dev/null
docker exec -i karag-test-pg psql -v ON_ERROR_STOP=1 -U postgres -d "$DB" \
    < build/pg_reader.sql >/dev/null
echo "  seeded: $(docker exec karag-test-pg psql -tAU postgres -d "$DB" -c 'SELECT count(*) FROM sales') sales rows"

# --- MySQL ----------------------------------------------------------------
step "Starting karag-test-mysql"
docker run -d --name karag-test-mysql --network "$NETWORK" \
    -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PW" -e MYSQL_DATABASE="$DB" \
    -p 127.0.0.1:53306:3306 \
    --restart unless-stopped \
    "$MYSQL_IMAGE" --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci >/dev/null

# A real query, not a ping: during initialisation the server answers a ping
# while root still has no password, and the seed then fails on access denied.
mysql_root() { docker exec -i -e MYSQL_PWD="$MYSQL_ROOT_PW" karag-test-mysql \
    mysql -uroot --default-character-set=utf8mb4 "$@"; }

printf '  waiting for mysql'
for _ in $(seq 1 120); do
    if mysql_root -e 'SELECT 1' >/dev/null 2>&1; then break; fi
    printf '.'; sleep 2
done; echo

# --default-character-set=utf8mb4 is not optional: without it the Cyrillic
# names arrive double-encoded and every later comparison looks broken.
mysql_root < build/apteka_mysql.sql
mysql_root < build/mysql_reader.sql
echo "  seeded: $(mysql_root -N -B -e "SELECT count(*) FROM $DB.sales") sales rows"

# --- dumps, for the "upload a dump" path ----------------------------------
step "Writing real dumps for the upload path"
docker exec karag-test-pg pg_dump -U postgres --no-owner --no-privileges "$DB" \
    > build/apteka_pg_dump.sql
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PW" karag-test-mysql \
    mysqldump -uroot --default-character-set=utf8mb4 --skip-comments --no-tablespaces "$DB" \
    > build/apteka_mysql_dump.sql
ls -lh build/*.sql build/apteka.db | awk '{printf "  %-42s %s\n", $9, $5}'

cat <<INFO

$(printf '\033[1mReady.\033[0m') From inside the platform's containers:

  API        http://karag-test-api:8100/v1/products
  Postgres   host karag-test-pg     port 5432   db $DB   user karag_reader / readonly
  MySQL      host karag-test-mysql  port 3306   db $DB   user karag_reader / readonly

From this machine: http://localhost:8100/v1/products, psql -h localhost -p 55432,
mysql -h 127.0.0.1 -P 53306. Files to upload are in testbench/build/.
INFO
