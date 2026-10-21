#!/usr/bin/env bash
set -euo pipefail

KEY="${APPLESPY_KEY:-$HOME/Desktop/id_rsa}"
HOST="${APPLESPY_HOST:-admin@193.180.210.11}"
SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

say "Собираю фронтенд"
(cd frontend && npm run build)

say "Пакую"
tar --exclude='.venv' --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.env' --exclude='probe_dump.json' \
    -czf /tmp/applespy-backend.tgz -C backend .
tar -czf /tmp/applespy-frontend.tgz -C frontend/dist .

say "Заливаю"
scp "${SSH_OPTS[@]}" /tmp/applespy-backend.tgz /tmp/applespy-frontend.tgz "$HOST:/tmp/"

say "Разворачиваю"
ssh "${SSH_OPTS[@]}" "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
cd /home/admin/applespy

tar -xzf /tmp/applespy-backend.tgz -C /home/admin/applespy
./venv/bin/pip install -q -r requirements.txt
./venv/bin/alembic upgrade head

sudo rm -rf /var/www/applespy.panoff.dev/assets
sudo tar -xzf /tmp/applespy-frontend.tgz -C /var/www/applespy.panoff.dev
sudo chown -R www-data:www-data /var/www/applespy.panoff.dev

sudo systemctl restart applespy-web applespy-worker applespy-bot
sleep 4
for s in applespy-web applespy-worker applespy-bot; do
  printf '%-20s %s\n' "$s" "$(systemctl is-active "$s")"
done
curl -s --max-time 10 http://127.0.0.1:8020/api/health; echo
REMOTE

say "Готово: https://applespy.panoff.dev"
