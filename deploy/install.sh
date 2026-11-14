#!/usr/bin/env bash
# Ubuntu/Debian sunucuya kurulum: ajanı arka planda 7/24 çalışan bir servis yapar.
#   bash deploy/install.sh
set -e
cd "$(dirname "$0")/.."
DIR="$(pwd)"; USER_NAME="$(whoami)"

echo ">> Paketler kuruluyor"
sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv >/dev/null
python3 -m venv venv
venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "WEB_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')" >> .env #
  echo ">> .env oluşturuldu. API anahtarlarını girin: nano $DIR/.env"
fi

echo ">> Servis oluşturuluyor"
sudo tee /etc/systemd/system/news-trader.service >/dev/null <<UNIT
[Unit]
Description=Haber Trade Ajani
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable news-trader >/dev/null

if command -v ufw >/dev/null && sudo ufw status | grep -q active; then sudo ufw allow 8080/tcp >/dev/null; fi

IP=$(curl -s -4 ifconfig.me || hostname -I | awk '{print $1}')
echo
echo "Kurulum tamam."
echo "  1) Anahtarları girin:      nano $DIR/.env"
echo "  2) Ayarları kontrol edin:  nano $DIR/config.yaml"
echo "  3) Başlatın:               sudo systemctl restart news-trader"
echo "  4) Telefondan açın:        http://$IP:8080"
echo "  Loglar:                    journalctl -u news-trader -f"
