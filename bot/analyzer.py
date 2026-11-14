"""Haberi Claude ile analiz eder: kripto için olumlu mu, olumsuz mu, hangi coin?"""
import logging

import anthropic

log = logging.getLogger("analyzer")

SYSTEM = """Sen kısa vadeli (dakikalar-saatler) kripto para fiyat etkisini değerlendiren bir haber analistisin.
Sana bir X/Twitter paylaşımı verilecek. Görevin:
1. Bu paylaşımın piyasayı hareket ettirebilecek GERÇEK ve YENİ bir haber olup olmadığına karar ver.
   Reklam, görüş, meme, eski haber tekrarı, belirsiz söylenti, soru, anket -> relevant=false.
2. Hangi coin(ler)i etkilediğini belirle (ticker: BTC, ETH, SOL...). Genel piyasa haberiyse (FED, ETF genel, regülasyon) market_wide=true.
3. Kısa vadeli fiyat etkisini skorla: -1 (çok olumsuz: hack, iflas, yasak, dava, büyük satış) ... +1 (çok olumlu: ETF onayı, büyük şirket alımı, listeleme, ortaklık).
4. confidence: Yönden ne kadar eminsin (0-1). Haber zaten fiyatlanmış olabilirse veya etkisi belirsizse düşük ver.
Abartma; emin değilsen düşük confidence ver. Yanlış işlem, kaçırılan işlemden daha kötüdür."""

TOOL = {
    "name": "report_analysis",
    "description": "Haber analiz sonucunu bildir.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant": {"type": "boolean", "description": "Piyasayı etkileyebilecek gerçek, yeni bir haber mi?"},
            "assets": {"type": "array", "items": {"type": "string"}, "description": "Etkilenen coin ticker'ları, büyük harf"},
            "market_wide": {"type": "boolean", "description": "Tüm kripto piyasasını etkileyen genel bir haber mi?"},
            "score": {"type": "number", "description": "-1 (çok olumsuz) ile +1 (çok olumlu) arası"},
            "confidence": {"type": "number", "description": "0-1 arası güven"},
            "reason": {"type": "string", "description": "Tek cümlelik gerekçe (Türkçe)"},
        },
        "required": ["relevant", "assets", "market_wide", "score", "confidence", "reason"],
    },
}


class Analyzer:
    def __init__(self, model: str, api_key: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    def analyze(self, username: str, text: str) -> dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            system=SYSTEM,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "report_analysis"},
            messages=[{"role": "user", "content": f"Kaynak: @{username}\nPaylaşım:\n{text}"}],
        )
        for block in msg.content:
            if block.type == "tool_use":
                res = dict(block.input)
                res["assets"] = [a.upper().lstrip("$") for a in res.get("assets", [])]
                res["score"] = max(-1.0, min(1.0, float(res.get("score", 0))))
                res["confidence"] = max(0.0, min(1.0, float(res.get("confidence", 0))))
                return res
        raise RuntimeError("Claude analiz döndürmedi")
