"""Vercel dışında (bilgisayar / VPS / Termux) çalıştırma.

  python run.py                                    # panel + her poll_seconds'ta bir haber turu
  python run.py --test "SEC approves Solana ETF"   # tek metni analiz et, işlem açmaz
"""
import argparse
import logging
import threading
import time

from app import agent, app, cfg

log = logging.getLogger("run")


def loop():
    while True:
        try:
            log.info("tur: %s", agent.tick())
        except Exception as e:
            log.exception("tur hatası: %s", e)
        time.sleep(cfg["poll_seconds"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="Bir haber metnini analiz et ve kararı göster (işlem açmaz)")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    if args.test:
        print(agent.test(args.test))
        return
    threading.Thread(target=loop, daemon=True).start()
    from waitress import serve
    log.info("Panel: http://0.0.0.0:%s", args.port)
    serve(app, host="0.0.0.0", port=args.port, threads=4)


if __name__ == "__main__":
    main()
