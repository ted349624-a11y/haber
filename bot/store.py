"""Kalıcı depolama. Vercel'de Upstash Redis (REST), bilgisayarda/sunucuda yerel JSON dosyası.

Vercel Marketplace'ten "Upstash for Redis" eklenince KV_REST_API_URL / KV_REST_API_TOKEN
(veya UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN) ortam değişkenleri otomatik gelir.
"""
import json
import os
import threading
import time

import requests


def get_store():
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return RedisStore(url, token)
    if os.getenv("VERCEL"):
        raise RuntimeError("Vercel'de Redis gerekli: Storage sekmesinden Upstash Redis ekleyin.")
    return FileStore(os.getenv("STORE_FILE", "store.json"))


class RedisStore:
    def __init__(self, url, token, prefix="ht:"):
        self.url, self.prefix = url.rstrip("/"), prefix
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def _cmd(self, *args):
        r = self.s.post(self.url, json=[str(a) for a in args], timeout=10)
        r.raise_for_status()
        return r.json().get("result")

    def _pipe(self, *cmds):
        r = self.s.post(self.url + "/pipeline", json=[[str(a) for a in c] for c in cmds], timeout=10)
        r.raise_for_status()
        return [x.get("result") for x in r.json()]

    def get(self, key, default=None):
        v = self._cmd("GET", self.prefix + key)
        return default if v is None else json.loads(v)

    def set(self, key, value):
        self._cmd("SET", self.prefix + key, json.dumps(value))

    def push(self, key, value, keep=300):
        self._pipe(["LPUSH", self.prefix + key, json.dumps(value)], ["LTRIM", self.prefix + key, 0, keep - 1])

    def items(self, key, n=50):
        return [json.loads(x) for x in (self._cmd("LRANGE", self.prefix + key, 0, n - 1) or [])]

    def incr(self, key, ttl):
        return int(self._pipe(["INCR", self.prefix + key], ["EXPIRE", self.prefix + key, ttl, "NX"])[0])

    def delete(self, key):
        self._cmd("DEL", self.prefix + key)

    def acquire(self, key, ttl):
        return self._cmd("SET", self.prefix + key, "1", "NX", "EX", ttl) == "OK"


class FileStore:
    """Tek süreçlik yerel kullanım için basit JSON dosyası."""
    _lock = threading.RLock()

    def __init__(self, path):
        self.path = path

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path) as f:
            return json.load(f)

    def _save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def _alive(self, d, key):
        exp = d.get("__ttl", {}).get(key)
        if exp and exp < time.time():
            d.pop(key, None)
            d["__ttl"].pop(key, None)
        return d.get(key)

    def get(self, key, default=None):
        with self._lock:
            v = self._alive(self._load(), key)
            return default if v is None else v

    def set(self, key, value):
        with self._lock:
            d = self._load(); d[key] = value; self._save(d)

    def push(self, key, value, keep=300):
        with self._lock:
            d = self._load(); d[key] = ([value] + d.get(key, []))[:keep]; self._save(d)

    def items(self, key, n=50):
        return (self.get(key) or [])[:n]

    def incr(self, key, ttl):
        with self._lock:
            d = self._load()
            v = (self._alive(d, key) or 0) + 1
            d[key] = v
            d.setdefault("__ttl", {}).setdefault(key, time.time() + ttl)
            self._save(d)
            return v

    def delete(self, key):
        with self._lock:
            d = self._load(); d.pop(key, None); d.get("__ttl", {}).pop(key, None); self._save(d)

    def acquire(self, key, ttl):
        with self._lock:
            d = self._load()
            if self._alive(d, key):
                return False
            d[key] = 1
            d.setdefault("__ttl", {})[key] = time.time() + ttl
            self._save(d)
            return True
