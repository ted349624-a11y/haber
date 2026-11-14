"""Vercel giriş noktası: Vercel bu dosyadaki `app` (Flask) nesnesini otomatik çalıştırır."""
import hashlib
import logging
import os

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from bot.agent import Agent
from bot.store import get_store
from bot.web import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-8s %(message)s")
BASE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    path = os.getenv("CONFIG_FILE") or os.path.join(BASE, "config.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if os.getenv("TRADE_MODE"):                       # modu Vercel ortam değişkeninden de değiştirebilirsiniz
        cfg["mode"] = os.getenv("TRADE_MODE")
    if os.getenv("LIVE_ONAY", "").lower() == "true":
        cfg["live_onay"] = True
    return cfg


cfg = load_config()
store = get_store()
agent = Agent(cfg, store)

WEB_CODE = os.getenv("WEB_CODE", "").strip()
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()
# Oturum anahtarı: WEB_SECRET yoksa gizli değerlerden türetilir (tüm Vercel örneklerinde aynı olsun diye)
SECRET = os.getenv("WEB_SECRET") or hashlib.sha256(
    f"ht-session|{WEB_CODE}|{CRON_SECRET}|{os.getenv('KV_REST_API_TOKEN', '')}|"
    f"{os.getenv('UPSTASH_REDIS_REST_TOKEN', '')}".encode()).hexdigest()

app = create_app(agent, WEB_CODE, SECRET, CRON_SECRET)
