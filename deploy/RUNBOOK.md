# RUNBOOK — развёртывание KGB_Bot на VPS

Подставьте свои значения вместо плейсхолдеров: `<user>`, `<server>`, `<ssh_port>`.

**Сервер:** `ssh -p <ssh_port> <user>@<server>` · **Каталог:** `~/KGB_Bot` · **venv:** `.venv` · **данные:** `data/` (вне git)

> Деплой соответствует юниту U14 плана.

---

## 0. Предусловия безопасности (KTD9 / Threat Model)

- **KB-репо `KGB_Bot_Materials` — приватный** (знания приватных чатов).
- Креды KB-репо — **deploy key или fine-grained PAT только на KGB_Bot_Materials**, не широкий classic PAT.
- `.env` на сервере — права `0600`, владелец `<user>`, **не в git**, исключён из бэкапов.
- `data/secretary.db` — права `0600`; бэкап шифровать при выносе с сервера.
- Бот в @BotFather: **выключить privacy mode** (или сделать админом чата) и
  переподключить к уже добавленным чатам — иначе он не видит обычные сообщения.
- Рекомендуется 2FA на админ-аккаунте Telegram; первый админ — через `ADMIN_USER_ID`.

---

## 1. Подготовка сервера (однократно)

Нужны Python 3.11+ и git. При необходимости:
```bash
ssh -p <ssh_port> <user>@<server>
sudo apt update && sudo apt install -y python3-venv git
mkdir -p ~/KGB_Bot
```

## 2. Доставка кода

Вариант A — клон репо (нужен git-доступ на сервере):
```bash
git clone <code-repo-url> ~/KGB_Bot
```
Вариант B — `rsync`/`scp` с локальной машины (см. `deploy/deploy.sh`; задайте `KGB_HOST=<user>@<server>` и при необходимости `KGB_PORT`).

## 3. Окружение

```bash
cd ~/KGB_Bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

## 4. Секреты

Скопировать `.env` с локальной машины **по защищённому каналу** и выставить права:
```bash
scp -P <ssh_port> .env <user>@<server>:~/KGB_Bot/.env
ssh -p <ssh_port> <user>@<server> 'chmod 600 ~/KGB_Bot/.env'
```
В `.env` заполнить: `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`,
(для синка знаний) `KB_REPO_URL` + `KB_REPO_DEPLOY_KEY_PATH`/`KB_REPO_TOKEN`,
`ADMIN_USER_ID`.

## 5. KB-репо (для синка знаний)

Сгенерировать deploy key, добавить публичную часть в `KGB_Bot_Materials`
(Settings → Deploy keys, **Allow write access**), приватную положить на сервер
`chmod 600`, путь указать в `KB_REPO_DEPLOY_KEY_PATH`:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/kgb_kb_deploy -N "" -C "kgb-bot-kb"
cat ~/.ssh/kgb_kb_deploy.pub   # добавить в Deploy keys (write)
```

## 6. systemd

**Без root (рекомендуется при `Linger=yes`)** — user-сервис `secretary-bot.user.service`
(не требует sudo, переживает ребут):
```bash
loginctl enable-linger "$USER"   # если ещё не включено
cp ~/KGB_Bot/deploy/secretary-bot.user.service ~/.config/systemd/user/secretary-bot.service
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user daemon-reload
systemctl --user enable --now secretary-bot
systemctl --user status secretary-bot
journalctl --user -u secretary-bot -f
```

**С root** — системный `secretary-bot.service` (подставьте `User=` и пути):
```bash
sudo cp ~/KGB_Bot/deploy/secretary-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now secretary-bot
```

## 7. Ввод в эксплуатацию

- Добавить бота в рабочие чаты (privacy mode off / админ).
- В личке от админа: `/newproject` → `/bindchat` → пообщаться → `/runextract`
  (или дождаться авто-извлечения планировщиком).

## Обновление

```bash
# новый код (git pull / rsync), затем:
.venv/bin/pip install -e .
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user restart secretary-bot
```

## Бэкап / откат

- Бэкап: `data/secretary.db` (зашифровать). KB-репо версионируется git'ом.
- Откат: вернуть прошлый коммит кода + `systemctl --user restart`; знания в KB-репо откатываются git'ом.
