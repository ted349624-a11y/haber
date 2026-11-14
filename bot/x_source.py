"""X (Twitter) API v2 üzerinden hesapların yeni paylaşımlarını çeker."""
import logging
import time
from datetime import datetime

import requests

log = logging.getLogger("x")
BASE = "https://api.x.com/2"


class XSource:
    def __init__(self, bearer_token: str, usernames: list[str], state):
        if not bearer_token:
            raise ValueError("X_BEARER_TOKEN eksik (.env)")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {bearer_token}"
        self.usernames = usernames
        self.state = state
        self.rate_limited_until = 0.0

    def _get(self, path, params):
        if time.time() < self.rate_limited_until:
            return None
        r = self.s.get(f"{BASE}{path}", params=params, timeout=15)
        if r.status_code == 429:
            reset = float(r.headers.get("x-rate-limit-reset", time.time() + 60))
            self.rate_limited_until = reset
            log.warning("X rate limit! %ds bekleniyor", int(reset - time.time()))
            return None
        r.raise_for_status()
        return r.json()

    def resolve_ids(self):
        missing = [u for u in self.usernames if u not in self.state.data["user_ids"]]
        if not missing:
            return
        data = self._get("/users/by", {"usernames": ",".join(missing)})
        for u in (data or {}).get("data", []):
            self.state.data["user_ids"][u["username"]] = u["id"]
            log.info("@%s -> id %s", u["username"], u["id"])

    def fetch_new(self) -> list[dict]:
        """Her hesabın son kontrolden beri attığı tweetleri döndürür (eskiden yeniye)."""
        self.resolve_ids()
        out = []
        for username, uid in self.state.data["user_ids"].items():
            if username not in self.usernames:
                continue
            since = self.state.data["since_ids"].get(username)
            params = {
                "max_results": 10 if since else 5,
                "exclude": "retweets,replies",
                "tweet.fields": "created_at,note_tweet",
            }
            if since:
                params["since_id"] = since
            data = self._get(f"/users/{uid}/tweets", params)
            if data is None:
                continue
            tweets = data.get("data", [])
            if tweets:
                self.state.data["since_ids"][username] = tweets[0]["id"]
            if not since:
                # İlk çalıştırma: eski haberlerle işlem açmamak için sadece işaretle
                log.info("@%s için başlangıç noktası ayarlandı", username)
                continue
            for t in reversed(tweets):
                text = (t.get("note_tweet") or {}).get("text") or t["text"]
                out.append({
                    "id": t["id"],
                    "username": username,
                    "text": text,
                    "created_at": datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
                })
        return out
