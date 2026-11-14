"""Analiz sonucunu işlem kararına çevirir. Saf mantık - test edilebilir."""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Decision:
    action: str          # "long" | "short" | "skip"
    asset: str | None
    reason: str


def decide(analysis: dict, tweet: dict, account_weight: float, cfg: dict, state) -> Decision:
    a_cfg, risk = cfg["analyzer"], cfg["risk"]

    age = (datetime.now(timezone.utc) - tweet["created_at"]).total_seconds()
    if age > cfg["max_tweet_age_seconds"]:
        return Decision("skip", None, f"haber çok eski ({int(age)}s)")

    if not analysis["relevant"]:
        return Decision("skip", None, "piyasa haberi değil")

    score = analysis["score"] * account_weight
    if analysis["confidence"] < a_cfg["min_confidence"]:
        return Decision("skip", None, f"güven düşük ({analysis['confidence']:.2f})")
    if abs(score) < a_cfg["min_abs_score"]:
        return Decision("skip", None, f"skor zayıf ({score:+.2f})")

    allowed = [x.upper() for x in cfg["allowed_assets"]]
    asset = next((x for x in analysis["assets"] if x in allowed), None)
    if asset is None and analysis.get("market_wide") and cfg.get("market_wide_asset"):
        asset = cfg["market_wide_asset"].upper()
    if asset is None:
        return Decision("skip", None, f"izinli coin yok ({analysis['assets']})")

    side = "long" if score > 0 else "short"
    pos = state.data["positions"].get(asset)
    if pos:
        if pos["side"] == side:
            return Decision("skip", asset, "aynı yönde pozisyon zaten açık")
        if not risk["reverse_on_opposite"]:
            return Decision("skip", asset, "ters pozisyon açık, reverse kapalı")
    elif len(state.data["positions"]) >= risk["max_open_positions"]:
        return Decision("skip", asset, "maks. açık pozisyon sayısına ulaşıldı")

    if state.trades_today() >= risk["max_trades_per_day"]:
        return Decision("skip", asset, "günlük işlem limiti doldu")
    if state.in_cooldown(asset, risk["cooldown_minutes"]):
        return Decision("skip", asset, "cooldown süresinde")

    return Decision(side, asset, f"skor {score:+.2f}, güven {analysis['confidence']:.2f}")
