# RSI값이 4시간 기준 35이하시, 또는 70이상시 텔레그램으로 전송

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
업비트 RSI 텔레그램 알림 봇 (원샷 실행)
- 60분봉 RSI(14) + 240분봉 RSI(14) 각각 계산 (업비트 4시간 차트와 일치)
- 알림 판단은 240분 RSI 기준 (RSI_LOWER/RSI_UPPER 환경변수로 조절)
- 하루 1번 하트비트(--heartbeat) 메시지
- systemd timer/service로 스케줄링 전제
"""

import os
import sys
import time
import argparse
import datetime
from typing import List, Tuple
from zoneinfo import ZoneInfo

import requests
import pandas as pd

# -----------------------------
# 설정/상수
# -----------------------------
UPBIT_MARKETS_URL = "https://api.upbit.com/v1/market/all"
UPBIT_CANDLES_MIN_URL = "https://api.upbit.com/v1/candles/minutes/{itv}"

DEFAULT_SELECTED_COINS = [
    'KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-SUI','KRW-TRUMP','KRW-USDT','KRW-ATOM',
    'KRW-DOGE', 'KRW-DOT', 'KRW-AVAX', 'KRW-LINK', 'KRW-TRX','KRW-ONDO', 'KRW-JUP','KRW-ME','KRW-ASTR',
    'KRW-SEI', 'KRW-SAND', 'KRW-CTC', 'KRW-GRT', 'KRW-HBAR', 'KRW-CRO','KRW-ETC','KRW-BONK', 'KRW-VET',
    'KRW-VIRTUAL'
]

REQ_TIMEOUT = 10
REQ_HEADERS = {"User-Agent": "upbit-rsi-bot/1.0"}

# -----------------------------
# 유틸
# -----------------------------
def get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def parse_coin_list(env_value: str) -> List[str]:
    if not env_value:
        return DEFAULT_SELECTED_COINS
    parts = [p.strip() for p in env_value.split(",")]
    return [p for p in parts if p]

# -----------------------------
# 텔레그램
# -----------------------------
def send_telegram_message(text: str, bot_token: str, chat_id: str) -> Tuple[bool, str]:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    last_err = ""
    for _ in range(3):
        try:
            resp = requests.post(url, params=params, headers=REQ_HEADERS, timeout=REQ_TIMEOUT)
            if resp.status_code == 200:
                return True, resp.text
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            last_err = f"Exception: {e}"
        time.sleep(1.0)
    return False, last_err

# -----------------------------
# 업비트 API
# -----------------------------
def fetch_candles_minutes(itv: int, symbol: str, count: int = 200) -> pd.DataFrame:
    url = UPBIT_CANDLES_MIN_URL.format(itv=itv)
    params = {"market": symbol, "count": str(count)}
    resp = requests.get(url, params=params, headers=REQ_HEADERS, timeout=REQ_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    df = pd.DataFrame(resp.json())
    if 'trade_price' not in df.columns:
        raise KeyError("trade_price column missing")
    df = df.sort_values(by="candle_date_time_kst").reset_index(drop=True)
    return df

# -----------------------------
# RSI (Wilder / RMA)
# -----------------------------
def rsi_wilder(ohlc: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = ohlc["trade_price"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return pd.Series(rsi, name="RSI")

# -----------------------------
# 핵심 로직 (원샷)
# -----------------------------
def check_and_alert_once(
    coins: List[str],
    bot_token: str,
    chat_id: str,
    request_interval: float = 0.8,
    itv_minutes_60: int = 60,
    itv_minutes_240: int = 240
) -> Tuple[int, int, int]:
    # 임계값
    try: rsi_lower = float(os.environ.get("RSI_LOWER", "35"))
    except: rsi_lower = 35.0
    try: rsi_upper = float(os.environ.get("RSI_UPPER", "70"))
    except: rsi_upper = 70.0
    if rsi_lower >= rsi_upper:
        rsi_lower, rsi_upper = 35.0, 70.0

    # 가격 필터
    def _to_int_or_none(v):
        if not v or v == "0": return None
        return int(str(v).replace(",", "").replace("_", ""))
    price_min = _to_int_or_none(os.environ.get("PRICE_MIN", "0"))
    price_max = _to_int_or_none(os.environ.get("PRICE_MAX", "0"))

    processed = alerts = failures = 0

    for symbol in coins:
        try:
            df60  = fetch_candles_minutes(itv_minutes_60,  symbol, count=200)
            df240 = fetch_candles_minutes(itv_minutes_240, symbol, count=200)

            rsi60  = round(rsi_wilder(df60,  14).iloc[-1], 1)
            rsi240 = round(rsi_wilder(df240, 14).iloc[-1], 1)

            price = int(df60["trade_price"].iloc[-1])
            coin  = symbol[4:]
            price_fmt = f"{price:,}원"

            if (price_min is not None and price < price_min) or \
               (price_max is not None and price > price_max):
                print(f"[INFO] Suppress by price filter: {symbol} {price_fmt}")
                processed += 1
                time.sleep(max(0.0, request_interval))
                continue

            action = None
            if rsi240 <= rsi_lower:
                action = "매수"
            elif rsi240 >= rsi_upper:
                action = "매도"

            if action:
                kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")
                msg = (
                    f"{coin} {price_fmt}\n"
                    f"RSI(60m/240m,14): {rsi60} / {rsi240}\n"
                    f"기준: {rsi_lower}/{rsi_upper}\n"
                    f"시간: {kst}\n"
                    f"액션: {action}"
                )
                ok, detail = send_telegram_message(msg, bot_token, chat_id)
                if ok:
                    alerts += 1
                    print(f"[INFO] ALERT sent: {symbol} | 60:{rsi60} 240:{rsi240} | {price_fmt}")
                else:
                    failures += 1
                    print(f"[WARN] ALERT send failed: {symbol} | {detail}")

            processed += 1

        except Exception as e:
            failures += 1
            print(f"[ERROR] processing {symbol}: {e}")

        time.sleep(max(0.0, request_interval))

    return processed, alerts, failures

# -----------------------------
# 하트비트
# -----------------------------
def send_heartbeat(bot_token: str, chat_id: str, coins: List[str]) -> None:
    import os
    utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")

    rsi_lower = os.getenv("RSI_LOWER", "35")
    rsi_upper = os.getenv("RSI_UPPER", "70")
    price_min = os.getenv("PRICE_MIN", "0")
    price_max = os.getenv("PRICE_MAX", "0")

    text = (
        "✅ RSI 봇 정상 동작 중\n\n"
        f"📊 코인 수: {len(coins)}개\n"
        f"⚙️ RSI 범위: {rsi_lower} ~ {rsi_upper}\n"
        f"💰 가격 필터: {price_min}원 ~ {price_max}원\n"
        f"⏰ 현재 시각: {utc} / {kst}\n"
    )
    ok, detail = send_telegram_message(text, bot_token, chat_id)
    if ok:
        print(f"[INFO] Heartbeat sent at {kst}")
    else:
        print(f"[WARN] Heartbeat send failed: {detail}")

# -----------------------------
# 메인
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Upbit RSI Telegram Bot (oneshot)")
    parser.add_argument("--heartbeat", action="store_true", help="하트비트 메시지 전송 모드")
    args = parser.parse_args()

    bot_token = get_env("BOT_TOKEN")
    chat_id   = get_env("CHAT_ID")
    if not bot_token or not chat_id:
        print("[ERROR] BOT_TOKEN/CHAT_ID 환경변수가 설정되지 않았습니다.")
        sys.exit(2)

    coins = parse_coin_list(get_env("SELECTED_COINS", ""))
    try:
        request_interval = float(get_env("REQUEST_INTERVAL", "0.8") or "0.8")
    except Exception:
        request_interval = 0.8

    if args.heartbeat:
        send_heartbeat(bot_token, chat_id, coins)
        return

    started = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[INFO] Job start (UTC): {started} | coins: {len(coins)}")

    processed, alerts, failures = check_and_alert_once(
        coins=coins,
        bot_token=bot_token,
        chat_id=chat_id,
        request_interval=request_interval,
        itv_minutes_60=60,
        itv_minutes_240=240,
    )

    finished = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[INFO] Job done (UTC): {finished} | processed={processed} alerts={alerts} failures={failures}")

if __name__ == "__main__":
    main()

