"""Borsa işlemleri (ccxt). dry_run modunda gerçek emir göndermez, kâğıt üzerinde takip eder."""
import logging
import time
from datetime import datetime, timezone

import ccxt

log = logging.getLogger("trader")


class Trader:
    def __init__(self, cfg: dict, state, store, keys: dict, notify=None):
        self.cfg, self.state, self.store = cfg, state, store
        self.notify = notify or (lambda text: None)
        self.mode = cfg["mode"]
        self.risk = cfg["risk"]
        self.quote = cfg["exchange"]["quote"]
        klass = getattr(ccxt, cfg["exchange"]["id"])
        opts = {"enableRateLimit": True, "timeout": 15000, "options": {"defaultType": "swap"}}
        if self.mode in ("testnet", "live"):
            if not keys.get("key") or not keys.get("secret"):
                raise RuntimeError("EXCHANGE_API_KEY / EXCHANGE_API_SECRET eksik")
            opts.update(apiKey=keys["key"], secret=keys["secret"])
            if keys.get("password"):
                opts["password"] = keys["password"]
        self.ex = klass(opts)
        if self.mode == "testnet":
            try:
                self.ex.set_sandbox_mode(True)
            except Exception:
                self.ex.enable_demo_trading(True)   # binance gibi borsalar için

    def symbol(self, asset: str) -> str:
        return f"{asset}/{self.quote}:{self.quote}"

    def price(self, asset: str) -> float:
        px = float(self.ex.fetch_ticker(self.symbol(asset))["last"])
        self.state.data["prices"][asset] = px          # panel bu önbellekten okur
        return px

    # ---------------- açma ----------------
    def open(self, asset: str, side: str, tweet: dict, analysis: dict):
        sym = self.symbol(asset)
        px = self.price(asset)
        notional = self.risk["usdt_per_trade"] * self.risk["leverage"]
        amount = float(self.ex.amount_to_precision(sym, notional / px))
        sl_k, tp_k = self.risk["stop_loss_pct"] / 100, self.risk["take_profit_pct"] / 100
        if side == "long":
            sl, tp, order_side, exit_side = px * (1 - sl_k), px * (1 + tp_k), "buy", "sell"
        else:
            sl, tp, order_side, exit_side = px * (1 + sl_k), px * (1 - tp_k), "sell", "buy"
        sl = float(self.ex.price_to_precision(sym, sl))
        tp = float(self.ex.price_to_precision(sym, tp))

        if self.mode != "dry_run":
            try:
                self.ex.set_leverage(self.risk["leverage"], sym)
            except Exception as e:
                log.warning("Kaldıraç ayarlanamadı: %s", e)
            order = self.ex.create_order(sym, "market", order_side, amount)
            px = float(order.get("average") or px)
            # Borsa tarafında koruyucu emirler (ajan çalışmasa bile çalışır)
            self.ex.create_order(sym, "market", exit_side, amount, None,
                                 {"stopLossPrice": sl, "reduceOnly": True})
            self.ex.create_order(sym, "market", exit_side, amount, None,
                                 {"takeProfitPrice": tp, "reduceOnly": True})

        self.state.data["positions"][asset] = {
            "side": side, "amount": amount, "entry": px, "sl": sl, "tp": tp,
            "opened_at": time.time(), "tweet_id": tweet["id"], "source": tweet["username"],
        }
        self.state.record_trade(asset)
        self._log("OPEN", asset, side, amount, px, None, tweet["username"], analysis["reason"])
        emoji = "🟢 LONG" if side == "long" else "🔴 SHORT"
        self.notify(f"{emoji} {asset} açıldı [{self.mode}] · giriş {px} · SL {sl} · TP {tp}\n"
                    f"@{tweet['username']}: {tweet['text'][:200]}")

    # ---------------- kapatma ----------------
    def close(self, asset: str, why: str, exit_px: float | None = None):
        pos = self.state.data["positions"].get(asset)
        if not pos:
            return None
        sym = self.symbol(asset)
        if self.mode != "dry_run":
            self._cancel_all(sym)
            live = self._live_position(sym)
            if live:
                exit_side = "sell" if pos["side"] == "long" else "buy"
                order = self.ex.create_order(sym, "market", exit_side, live, None, {"reduceOnly": True})
                exit_px = float(order.get("average") or 0) or None
        exit_px = exit_px or self.price(asset)
        sign = 1 if pos["side"] == "long" else -1
        pnl = sign * (exit_px - pos["entry"]) * pos["amount"]
        self._log("CLOSE", asset, pos["side"], pos["amount"], exit_px, pnl, pos["source"], why)
        del self.state.data["positions"][asset]
        self.notify(f"{'✅' if pnl >= 0 else '❌'} {asset} {pos['side'].upper()} kapandı · "
                    f"çıkış {exit_px} · PnL ≈ {pnl:+.2f} USDT · {why}")
        return pnl

    # ---------------- takip ----------------
    def manage(self):
        """SL/TP/süre kontrolü. Her tetiklemede çağrılır."""
        max_age = self.risk["max_hold_minutes"] * 60
        for asset, pos in list(self.state.data["positions"].items()):
            try:
                if self.mode != "dry_run" and not self._live_position(self.symbol(asset)):
                    self._cancel_all(self.symbol(asset))
                    self.close(asset, "borsada SL/TP tetiklendi")
                    continue
                px = self.price(asset)
                if self.mode == "dry_run":
                    long = pos["side"] == "long"
                    if (long and px <= pos["sl"]) or (not long and px >= pos["sl"]):
                        self.close(asset, "stop-loss", pos["sl"]); continue
                    if (long and px >= pos["tp"]) or (not long and px <= pos["tp"]):
                        self.close(asset, "take-profit", pos["tp"]); continue
                if time.time() - pos["opened_at"] > max_age:
                    self.close(asset, "süre doldu")
            except Exception as e:
                self.notify(f"⚠️ {asset} yönetilirken hata: {e}")

    def _live_position(self, sym) -> float:
        for p in self.ex.fetch_positions([sym]):
            c = float(p.get("contracts") or 0)
            if c:
                return c
        return 0.0

    def _cancel_all(self, sym):
        for params in ({}, {"stop": True}, {"trigger": True}):
            try:
                self.ex.cancel_all_orders(sym, params)
            except Exception:
                pass

    def _log(self, event, asset, side, amount, price, pnl, source, note):
        self.store.push("trades", {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": self.mode,
            "event": event, "asset": asset, "side": side, "amount": amount, "price": price,
            "pnl": None if pnl is None else round(pnl, 4), "source": source, "note": note,
        }, keep=1000)
