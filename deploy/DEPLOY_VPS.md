# VPS Deployment Guide

## 1. Prerequisites

- Ubuntu 22.04+ VPS
- Domain A-record pointed to VPS IP (example: `bot.example.com`)
- Installed: `docker`, `docker compose`, `nginx`, `certbot`, `python3-certbot-nginx`

## 2. Prepare project files

1. Upload project to `/opt/telegram-ai-reminder-bot`.
2. Copy env template:
   - `cp /opt/telegram-ai-reminder-bot/deploy/.env.prod.example /opt/telegram-ai-reminder-bot/deploy/.env.prod`
3. Fill real values in `/opt/telegram-ai-reminder-bot/deploy/.env.prod`.

## 3. Start application stack

Run:

```bash
cd /opt/telegram-ai-reminder-bot/deploy
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
```

## 4. Configure nginx

1. Copy config:
   - `sudo cp /opt/telegram-ai-reminder-bot/deploy/nginx/telegram-bot.conf /etc/nginx/sites-available/telegram-bot.conf`
2. Edit domain in config (`bot.example.com` -> your domain).
3. Enable site:
   - `sudo ln -s /etc/nginx/sites-available/telegram-bot.conf /etc/nginx/sites-enabled/telegram-bot.conf`
4. Check and reload:
   - `sudo nginx -t`
   - `sudo systemctl reload nginx`

## 5. TLS certificate (Let's Encrypt)

```bash
sudo certbot --nginx -d bot.example.com -m admin@example.com --agree-tos --no-eff-email
```

Replace domain and email with your values.

## 6. Register Telegram webhook

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://bot.example.com/webhook/telegram","secret_token":"<TELEGRAM_WEBHOOK_SECRET>"}'
```

## 7. Enable autostart with systemd

```bash
sudo cp /opt/telegram-ai-reminder-bot/deploy/systemd/telegram-reminder-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram-reminder-bot
sudo systemctl start telegram-reminder-bot
```

## 8. Smoke checks

- API health:
  - `curl http://127.0.0.1:8000/healthz`
- nginx TLS:
  - `curl -I https://bot.example.com/healthz`
- App logs:
  - `docker compose -f /opt/telegram-ai-reminder-bot/deploy/docker-compose.prod.yml logs -f app`
