# RSI값이 4시간 기준 30이하시, 또는 70이상시 텔레그램으로 전송

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
업비트 RSI 텔레그램 알림 봇 (원샷 실행 버전)
- 요구사항 반영:
  1) "한 번 실행하고 종료" 구조 (while True 제거)
  2) 하루 1번 "살아있음(하트비트)" 메시지: --heartbeat 옵션으로 같은 파일 재사용
  3) 재부팅 자동실행은 systemd timer/service에서 처리하기 좋도록
     - 환경변수로 토큰/채팅ID/코인리스트를 받도록 변경
     - 표준출력으로 요약 로그 남김( journald 에 쌓임 )

사용 예:
  # 1시간에 1번 RSI 체크 (systemd timer가 호출)
  python3 upbit_rsi.py

  # 하루 1번 하트비트(별도 timer가 호출)
  python3 upbit_rsi.py --heartbeat

환경변수(권장: /etc/default/upbit-rsi 같은 파일에 저장 후 service에서 EnvironmentFile=로 주입):
  BOT_TOKEN        = 텔레그램 봇 토큰
  CHAT_ID          = 텔레그램 수신 채팅 ID
  SELECTED_COINS   = "KRW-BTC,KRW-ETH,KRW-XRP" (쉼표 구분, 공백 허용)
  REQUEST_INTERVAL = 코인별 API 딜레이 초(기본 0.8초)

설치 필요 라이브러리:
  pip install requests pandas
"""


import os
import sys
import time
import json
import math
import argparse
import datetime
from zoneinfo import ZoneInfo  # Python 3.9+
from typing import List, Tuple

import requests
import pandas as pd


# -----------------------------
# 설정/상수
# -----------------------------
UPBIT_MARKETS_URL = "https://api.upbit.com/v1/market/all"
UPBIT_CANDLES_MIN_URL = "https://api.upbit.com/v1/candles/minutes/{itv}"

# 기본 코인 목록 (환경변수 SELECTED_COINS가 없을 때 사용)
DEFAULT_SELECTED_COINS = [
    'KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-SUI','KRW-TRUMP','KRW-USDT','KRW-ATOM',
    'KRW-DOGE', 'KRW-DOT', 'KRW-AVAX', 'KRW-LINK', 'KRW-TRX','KRW-ONDO', 'KRW-JUP','KRW-ME','KRW-ASTR',
    'KRW-SEI', 'KRW-SAND', 'KRW-CTC', 'KRW-GRT', 'KRW-HBAR', 'KRW-CRO','KRW-ETC','KRW-BONK', 'KRW-VET',
    'KRW-VIRTUAL'
]

# 요청 공통 타임아웃/헤더
REQ_TIMEOUT = 10  # 초
REQ_HEADERS = {
    "User-Agent": "upbit-rsi-bot/1.0 (+https://example.local)"  # 예의상 UA 지정
}


# -----------------------------
# 유틸: 환경변수 읽기/파싱
# -----------------------------
def get_env(name: str, default: str = "") -> str:
    """환경변수 읽기(없으면 default 반환)"""
    return os.environ.get(name, default).strip()


def parse_coin_list(env_value: str) -> List[str]:
    """쉼표로 구분된 코인 리스트 파싱 (공백 제거, 빈 값 제거)"""
    if not env_value:
        return DEFAULT_SELECTED_COINS
    parts = [p.strip() for p in env_value.split(",")]
    return [p for p in parts if p]


# -----------------------------
# 텔레그램
# -----------------------------
def send_telegram_message(text: str, bot_token: str, chat_id: str) -> Tuple[bool, str]:
    """
    텔레그램 메시지 전송 (간단 백오프 재시도 포함)
    반환: (성공여부, 응답문자열/에러메시지)
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    # 재시도(최대 3회, 고정 백오프)
    last_err = ""
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, params=params, headers=REQ_HEADERS, timeout=REQ_TIMEOUT)
            if resp.status_code == 200:
                return True, resp.text
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            last_err = f"Exception: {e}"

        # 실패 시 1.0s 대기 후 재시도
        time.sleep(1.0)
    return False, last_err


# -----------------------------
# 업비트
# -----------------------------
def get_krw_coins() -> List[str]:
    """전체 마켓 중 'KRW-'로 시작하는 심볼만 리스트로 반환"""
    try:
        resp = requests.get(UPBIT_MARKETS_URL, headers=REQ_HEADERS, timeout=REQ_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return [m['market'] for m in data if m.get('market', '').startswith('KRW-')]
    except Exception as e:
        print(f"[ERROR] get_krw_coins: {e}")
        return []


def fetch_candles_minutes(itv: int, symbol: str, count: int = 200) -> pd.DataFrame:
    """
    분봉 캔들 데이터(최근 N개) 요청 → DataFrame 반환
    itv: 1,3,5,15,30,60,240 등 (우리는 60 사용)
    """
    url = UPBIT_CANDLES_MIN_URL.format(itv=itv)
    params = {"market": symbol, "count": str(count)}
    try:
        resp = requests.get(url, params=params, headers=REQ_HEADERS, timeout=REQ_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        df = pd.DataFrame(resp.json())
        if 'trade_price' not in df.columns:
            raise KeyError("trade_price column missing")
        # 시간 오름차순 정렬(최신이 마지막)
        df = df.sort_values(by="candle_date_time_kst").reset_index(drop=True)
        return df
    except Exception as e:
        raise RuntimeError(f"fetch_candles_minutes error for {symbol} {itv}m: {e}")


# -----------------------------
# RSI 계산
# -----------------------------
def rsi_calc(ohlc: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    RSI 계산. 결과는 시리즈(인덱스 동일), 마지막 값이 최신 RSI.
    - 지수이동평균(EMA) 방식
    """
    # 원본 코드 호환을 위해 남겨두는 필드(실제 계산엔 'trade_price'만 사용)
    ohlc["trad_price"] = ohlc["trade_price"]

    delta = ohlc["trade_price"].diff()
    gains = delta.clip(lower=0)          # 상승폭(음수면 0)
    declines = (-delta).clip(lower=0)    # 하락폭 절대값

    _gain = gains.ewm(com=(period - 1), min_periods=period).mean()
    _loss = declines.ewm(com=(period - 1), min_periods=period).mean()

    RS = _gain / _loss
    rsi = 100 - (100 / (1 + RS))
    return pd.Series(rsi, name="RSI")


# -----------------------------
# 핵심 로직(원샷 실행)
# -----------------------------
def check_and_alert_once(
    coins: List[str],
    bot_token: str,
    chat_id: str,
    request_interval: float = 0.8,
    itv_minutes: int = 60
) -> Tuple[int, int, int]:
    """
    선택된 코인들에 대해 1회만 RSI 체크하고 조건 충족 시 텔레그램 알림.
    반환: (처리한 코인수, 알림건수, 실패건수)
    """
    processed = 0
    alerts = 0
    failures = 0

    for symbol in coins:
        try:
            df = fetch_candles_minutes(itv_minutes, symbol, count=200)

            # RSI(60분 기준 14, 240분 기준 56)
            nrsi_60 = round(rsi_calc(df, 14).iloc[-1], 1)
            nrsi_240 = round(rsi_calc(df, 56).iloc[-1], 1)

            # 현재가 (마지막 캔들의 종가)
            current_price = int(df['trade_price'].iloc[-1])
            price_formatted = f"{current_price:,}원"
            coin_name = symbol[4:]  # "KRW-" 제거

            # 조건 판정 및 전송
            msg = None
            if nrsi_240 <= 30:
                msg = f"{coin_name} {price_formatted}\n60분: {nrsi_60}, 240분: {nrsi_240}, 매수"
            elif nrsi_240 >= 70:
                msg = f"{coin_name} {price_formatted}\n60분: {nrsi_60}, 240분: {nrsi_240}, 매도"

            if msg:
                ok, detail = send_telegram_message(msg, bot_token, chat_id)
                if ok:
                    alerts += 1
                    print(f"[INFO] ALERT sent: {symbol} | 60:{nrsi_60} 240:{nrsi_240} | {price_formatted}")
                else:
                    failures += 1
                    print(f"[WARN] ALERT send failed: {symbol} | {detail}")

            processed += 1

        except Exception as e:
            failures += 1
            print(f"[ERROR] processing {symbol}: {e}")

        # API 연속 호출 사이 살짝 쉬기(레이트리밋 완화)
        time.sleep(max(0.0, request_interval))

    return processed, alerts, failures


def send_heartbeat(bot_token: str, chat_id: str, coins: List[str]) -> None:
    """
    하루 1번 호출되는 하트비트 전용 엔트리
    - 현재 시간을 KST로 찍고, 코인 개수 등 간단 요약 전송
    """
    kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    ts = kst.strftime("%Y-%m-%d %H:%M:%S KST")
    text = f"✅ RSI 봇 정상 동작 중\n시각: {ts}\n코인 수: {len(coins)}개"
    ok, detail = send_telegram_message(text, bot_token, chat_id)
    if ok:
        print(f"[INFO] Heartbeat sent at {ts}")
    else:
        print(f"[WARN] Heartbeat send failed: {detail}")


# -----------------------------
# 메인
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Upbit RSI Telegram Bot (oneshot)")
    parser.add_argument("--heartbeat", action="store_true", help="하트비트 메시지 전송 모드")
    args = parser.parse_args()

    # 필수 환경변수
    bot_token = get_env("BOT_TOKEN")
    chat_id = get_env("CHAT_ID")
    if not bot_token or not chat_id:
        print("[ERROR] BOT_TOKEN/CHAT_ID 환경변수가 설정되지 않았습니다.")
        sys.exit(2)

    # 코인 목록/요청 간격
    coins = parse_coin_list(get_env("SELECTED_COINS", ""))
    try:
        request_interval = float(get_env("REQUEST_INTERVAL", "0.8") or "0.8")
    except Exception:
        request_interval = 0.8

    if args.heartbeat:
        # 하루 1회 타이머로 이 모드를 호출
        send_heartbeat(bot_token, chat_id, coins)
        return

    # 원샷 RSI 체크 실행
    started = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[INFO] Job start (UTC): {started} | coins: {len(coins)}")

    processed, alerts, failures = check_and_alert_once(
        coins=coins,
        bot_token=bot_token,
        chat_id=chat_id,
        request_interval=request_interval,
        itv_minutes=60
    )

    finished = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[INFO] Job done (UTC): {finished} | processed={processed} alerts={alerts} failures={failures}")


if __name__ == "__main__":
    main()
