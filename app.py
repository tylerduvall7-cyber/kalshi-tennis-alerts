import os
import asyncio
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv

load_dotenv()

# =========================
# CONFIG
# =========================

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL")
PUSHOVER_APP_TOKEN = os.getenv("PUSHOVER_APP_TOKEN")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")

OPENING_THRESHOLD = 0.65
DROP_THRESHOLD = 0.50
FIRST_SET_WINDOW_MINUTES = 30

POLL_SECONDS = 8
DROP_CONFIRM_TICKS = 2


# =========================
# PUSH NOTIFICATIONS
# =========================

async def push_alert(title, message):
    url = "https://api.pushover.net/1/messages.json"
    payload = {
        "token": PUSHOVER_APP_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, data=payload)


# =========================
# KALSHI HELPERS
# =========================

async def kalshi_get(path, params=None):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{KALSHI_BASE_URL}{path}", params=params)
        r.raise_for_status()
        return r.json()


def normalize_price(price):
    if price is None:
        return None
    return price / 100 if price > 1 else price


async def get_yes_price(ticker):
    data = await kalshi_get(f"/markets/{ticker}/orderbook")
    asks = data.get("orderbook", {}).get("yes_asks", [])
    if not asks:
        return None
    return normalize_price(asks[0][0])


# =========================
# MAIN LOOP
# =========================

async def main():
    tracked = {}
    print("Kalshi Tennis Alerts running...")

    while True:
        try:
            markets = await kalshi_get("/markets", params={"status": "open", "limit": 500})
            now = datetime.now(timezone.utc)

            for m in markets.get("markets", []):
                ticker = m.get("ticker")
                title = m.get("title", "")
                open_time = m.get("open_time")

                if not ticker or "tennis" not in title.lower():
                    continue

                opened_at = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                minutes_live = (now - opened_at).total_seconds() / 60

                if minutes_live > FIRST_SET_WINDOW_MINUTES:
                    continue

                # New market
                if ticker not in tracked:
                    opening_price = await get_yes_price(ticker)
                    if opening_price and opening_price >= OPENING_THRESHOLD:
                        tracked[ticker] = {
                            "title": title,
                            "opened_at": opened_at,
                            "opening_price": opening_price,
                            "alerted": False,
                            "below_50_ticks": 0,
                        }
                        print(f"Tracking {title} ({opening_price:.0%})")

                # Existing market
                else:
                    if tracked[ticker]["alerted"]:
                        continue

                    live_price = await get_yes_price(ticker)
                    if live_price is None:
                        continue

                    if live_price < DROP_THRESHOLD:
                        tracked[ticker]["below_50_ticks"] += 1
                    else:
                        tracked[ticker]["below_50_ticks"] = 0

                    if tracked[ticker]["below_50_ticks"] >= DROP_CONFIRM_TICKS:
                        tracked[ticker]["alerted"] = True

                        msg = (
                            f"{tracked[ticker]['title']}\n\n"
                            f"Opened: {tracked[ticker]['opening_price']:.0%}\n"
                            f"Now: {live_price:.0%}\n"
                            f"Minutes in: {int(minutes_live)}\n"
                            f"Ticker: {ticker}"
                        )

                        await push_alert("🎾 Kalshi Tennis Alert", msg)
                        print("ALERT SENT:", tracked[ticker]["title"])

            await asyncio.sleep(POLL_SECONDS)

        except Exception as e:
            print("Error:", e)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
