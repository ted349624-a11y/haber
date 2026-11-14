"""Ajanın çekirdeği. Sürekli döngü yerine her çağrıda tek bir tur ('tick') çalışır:
Vercel'de dış zamanlayıcı (cron-job.org vb.) dakikada bir /api/tick adresini çağırır.
"""
import logging
import os
import time
from datetime import datetime, timezone

from bot.decision import decide
from bot.state import State

log = logging.getLogger("agent")
LOCK_TTL = 280


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Agent:
    def __init__(self, cfg: dict, store):
        self.cfg, self.store = cfg, store
        self.weights = {a["username"]: a.get("weight", 1.0) for a in cfg["accounts"]}
        self._analyzer = None

    # ---------------- yardımcılar ----------------
    def event(self, kind: str, text: str):
        log.info("[%s] %s", kind, text.replace("\n", " | "))
        try:
            self.store.push("events", {"t": now_iso(), "kind": kind, "text": text}, keep=300)
        except Exception as e:
            log.error("Olay kaydedilemedi: %s", e)

    @property
    def analyzer(self):
        if self._analyzer is None:
            from bot.analyzer import Analyzer
            self._analyzer = Analyzer(self.cfg["analyzer"]["model"], os.getenv("ANTHROPIC_API_KEY"))
        return self._analyzer

    def _trader(self, state):
        from bot.trader import Trader
        return Trader(self.cfg, state, self.store,
                      {"key": os.getenv("EXCHANGE_API_KEY"), "secret": os.getenv("EXCHANGE_API_SECRET"),
                       "password": os.getenv("EXCHANGE_API_PASSWORD")},
                      notify=lambda text: self.event("trade", text))

    def _locked(self, wait: float = 0):
        """Aynı anda iki tur çalışmasın (çift işlem açılmasın diye)."""
        deadline = time.time() + wait
        while not self.store.acquire("lock", LOCK_TTL):
            if time.time() >= deadline:
                return False
            time.sleep(1)
        return True

    # ---------------- tek tur ----------------
    def tick(self) -> dict:
        if self.cfg["mode"] == "live" and not self.cfg.get("live_onay"):
            return {"ok": False, "error": "live mod için config.yaml içinde live_onay: true gerekli"}
        if not self._locked():
            return {"ok": True, "skipped": "başka bir tur zaten çalışıyor"}
        state, n_new = State(self.store), 0
        try:
            from bot.x_source import XSource
            xs = XSource(os.getenv("X_BEARER_TOKEN"), list(self.weights), state)
            trader = self._trader(state)
            for tw in xs.fetch_new():
                if state.is_processed(tw["id"]):
                    continue
                state.mark_processed(tw["id"])
                n_new += 1
                if state.data["paused"]:
                    self.event("skip", f"@{tw['username']}: {tw['text'][:120]} → duraklatıldı, analiz edilmedi")
                    continue
                self._handle(tw, state, trader)
            trader.manage()
            state.data["last_error"] = None
            return {"ok": True, "new_tweets": n_new, "open_positions": len(state.data["positions"])}
        except Exception as e:
            state.data["last_error"] = str(e)[:300]
            self.event("error", f"Tur hatası: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            state.data["last_poll"] = now_iso()
            state.save()
            self.store.delete("lock")

    def _handle(self, tw, state, trader):
        try:
            res = self.analyzer.analyze(tw["username"], tw["text"])
        except Exception as e:
            self.event("error", f"Analiz hatası: {e}")
            return
        d = decide(res, tw, self.weights.get(tw["username"], 1.0), self.cfg, state)
        self.event("news" if d.action == "skip" else "signal",
                   f"@{tw['username']}: {tw['text'][:200]}\n"
                   f"skor {res['score']:+.2f} · güven {res['confidence']:.2f} → "
                   f"{d.action.upper()} {d.asset or ''} ({d.reason})\n{res['reason']}")
        if d.action in ("long", "short"):
            try:
                if d.asset in state.data["positions"]:
                    trader.close(d.asset, "ters haber geldi")
                trader.open(d.asset, d.action, tw, res)
            except Exception as e:
                self.event("error", f"{d.asset} işlemi açılamadı: {e}")

    # ---------------- web panel fonksiyonları ----------------
    def status(self) -> dict:
        state = State(self.store)
        positions, total = [], 0.0
        for asset, p in state.data["positions"].items():
            px = state.data["prices"].get(asset)
            pnl = None if px is None else (1 if p["side"] == "long" else -1) * (px - p["entry"]) * p["amount"]
            total += pnl or 0
            positions.append({**p, "asset": asset, "price": px,
                              "pnl": None if pnl is None else round(pnl, 2),
                              "minutes": round((time.time() - p["opened_at"]) / 60)})
        trades = self.store.items("trades", 1000)
        realized = sum(t["pnl"] or 0 for t in trades if t["event"] == "CLOSE" and t["mode"] == self.cfg["mode"])
        return {
            "mode": self.cfg["mode"], "paused": state.data["paused"],
            "last_poll": state.data["last_poll"], "last_error": state.data["last_error"],
            "trades_today": state.trades_today(), "max_trades_per_day": self.cfg["risk"]["max_trades_per_day"],
            "realized_pnl": round(realized, 2), "unrealized_pnl": round(total, 2),
            "positions": positions, "events": self.store.items("events", 60), "trades": trades[:30],
            "accounts": list(self.weights), "risk": self.cfg["risk"], "poll_seconds": self.cfg["poll_seconds"],
        }

    def set_paused(self, value: bool):
        if not self._locked(wait=25):
            raise RuntimeError("Ajan şu an meşgul, birkaç saniye sonra tekrar deneyin")
        try:
            state = State(self.store)
            state.data["paused"] = value
            state.save()
        finally:
            self.store.delete("lock")
        self.event("info", "Yeni işlemler DURAKLATILDI" if value else "Yeni işlemler DEVAM ediyor")

    def close(self, asset: str):
        if not self._locked(wait=25):
            raise RuntimeError("Ajan şu an meşgul, birkaç saniye sonra tekrar deneyin")
        state = State(self.store)
        try:
            trader = self._trader(state)
            targets = list(state.data["positions"]) if asset == "ALL" else [asset.upper()]
            for a in targets:
                if a in state.data["positions"]:
                    trader.close(a, "web panelden elle kapatıldı")
        finally:
            state.save()
            self.store.delete("lock")

    def test(self, text: str) -> dict:
        tw = {"id": "test", "username": "test", "text": text, "created_at": datetime.now(timezone.utc)}
        res = self.analyzer.analyze("test", text)
        d = decide(res, tw, 1.0, self.cfg, State(self.store))
        return {"analysis": res, "decision": {"action": d.action, "asset": d.asset, "reason": d.reason}}
