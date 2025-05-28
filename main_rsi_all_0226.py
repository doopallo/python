# RSI값이 4시간 기준 30이하시, 또는 70이상시 텔레그램으로 전송

import requests
import time
import pandas as pd

# 텔레그램 봇에 메시지를 보내는 함수
def send_telegram_message(message):
    bot_token = '봇 토큰을 여기에 입력하세요'  # 봇 토큰을 여기에 입력하세요
    chat_id = '채팅 id를 입력하세요'  # 채팅 ID를 여기에 입력하세요
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    params = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    response = requests.post(url, params=params)
    return response.json()

# 업비트에서 모든 한국 원(KRW) 코인을 가져오는 함수
def get_krw_coins():
    url = "https://api.upbit.com/v1/market/all"
    response = requests.get(url)
    data = response.json()
    krw_coins = [market['market'] for market in data if market['market'].startswith('KRW-')]
    return krw_coins

# 특정 코인에 대해 RSI 값을 계산하고 출력하는 함수
def rsi_upbit(itv, symbol):
    url = f"https://api.upbit.com/v1/candles/minutes/{itv}"
    querystring = {"market" : symbol, "count" : "200"}
    response = requests.request("GET", url, params=querystring)
    data = response.json()
    df = pd.DataFrame(data)
    df = df.reindex(index=df.index[::-1]).reset_index()
    nrsi_60 = round(rsi_calc(df, 14).iloc[-1], 1)
    nrsi_240 = round(rsi_calc(df, 56).iloc[-1], 1)
    
    if nrsi_240 <= 30:    # 60분 봉의 RSI 값이 40 이하이거나 240분 봉의 RSI 값이 70 이상인 경우에만 출력
        message = f"{symbol[4:]}, \n60분: {nrsi_60}, 240분: {nrsi_240}, 매수"
        send_telegram_message(message)
    if nrsi_240 >= 70:  # 60분 봉의 RSI 값이 40 이하이거나 240분 봉의 RSI 값이 70 이상인 경우에만 출력
        message = f"{symbol[4:]}, \n60분: {nrsi_60}, 240분: {nrsi_240}, 매도"
        send_telegram_message(message)

# OHLC 데이터프레임을 이용하여 RSI 값을 계산하는 함수
def rsi_calc(ohlc: pd.DataFrame, period: int = 14):
    ohlc["trad_price"] = ohlc["trade_price"]
    delta = ohlc["trade_price"].diff()
    gains, declines = delta.copy(), delta.copy()
    gains[gains < 0] = 0
    declines[declines > 0] = 0

    _gain = gains.ewm(com=(period-1), min_periods=period).mean()
    _loss = declines.abs().ewm(com=(period-1), min_periods=period).mean()

    RS = _gain / _loss
    return pd.Series(100-(100/(1+RS)), name="RSI")    

# test
krw_coins = get_krw_coins()
for coin in krw_coins:
    rsi_upbit(60, coin)
    time.sleep(1)
