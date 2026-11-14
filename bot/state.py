"""Ajan durumu: işlenen tweetler, açık pozisyonlar, cooldown'lar. Store içinde tek JSON olarak tutulur."""
import copy
import time
from datetime import datetime, timezone

DEFAULTS = {
    "user_ids": {}, "since_ids": {}, "processed": [], "positions": {},
    "last_trade_at": {}, "day": "", "trades_today": 0, "paused": False,
    "last_poll": None, "last_error": None, "prices": {},
}


class State:
    def __init__(self, store):
        self.store = store
        self.data = {**copy.deepcopy(DEFAULTS), **(store.get("state") or {})}

    def save(self):
        self.store.set("state", self.data)

    def is_processed(self, tweet_id: str) -> bool:
        return tweet_id in self.data["processed"]

    def mark_processed(self, tweet_id: str):
        self.data["processed"].append(tweet_id)
        self.data["processed"] = self.data["processed"][-1000:]

    def _roll_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.data["day"] != today:
            self.data["day"] = today
            self.data["trades_today"] = 0

    def trades_today(self) -> int:
        self._roll_day()
        return self.data["trades_today"]

    def record_trade(self, asset: str):
        self._roll_day()
        self.data["trades_today"] += 1
        self.data["last_trade_at"][asset] = time.time()

    def in_cooldown(self, asset: str, minutes: float) -> bool:
        return time.time() - self.data["last_trade_at"].get(asset, 0) < minutes * 60
