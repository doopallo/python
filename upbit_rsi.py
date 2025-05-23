# RSI값이 4시간 기준 30이하시, 또는 70이상시 텔레그램으로 전송

import requests
import time
import pandas as pd

# 텔레그램 봇에 메시지를 보내는 함수
def send_telegram_message(message):
    bot_token = '6804254258:AAHZzOgWz0mzv-VRiW74AIroOZnTFxqu3w8'  # 봇 토큰을 여기에 입력하세요
    chat_id = '440276118'  # 채팅 ID를 여기에 입력하세요
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    params = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    response = requests.post(url, params=params)
    return response.json()

# 업비트에서 모든 한국 원(KRW) 마켓의 코인 목록을 가져오는 함수
def get_krw_coins():
    url = "https://api.upbit.com/v1/market/all"
    response = requests.get(url)
    data = response.json()
    # 'KRW-'로 시작하는 마켓만 필터링
    krw_coins = [market['market'] for market in data if market['market'].startswith('KRW-')]
    return krw_coins

# 특정 코인의 RSI 값을 계산하고, 조건에 따라 텔레그램으로 알림을 보내는 함수
def rsi_upbit(itv, symbol):
    url = f"https://api.upbit.com/v1/candles/minutes/{itv}"
    querystring = {"market" : symbol, "count" : "200"}  # 최근 200개의 캔들 데이터를 가져옴
    response = requests.request("GET", url, params=querystring)
    data = response.json()
    df = pd.DataFrame(data)

    # 'trade_price' 컬럼 존재 여부 확인
    if 'trade_price' not in df.columns:
        print(f"⚠️ trade_price 누락: {symbol}")
        return

    # 시간 순으로 정렬
    df = df.sort_values(by="candle_date_time_kst").reset_index(drop=True)

    # 60분과 240분 RSI 계산
    nrsi_60 = round(rsi_calc(df, 14).iloc[-1], 1)       # 14기간 기준 RSI
    nrsi_240 = round(rsi_calc(df, 56).iloc[-1], 1)      # 56기간 기준 RSI (4배)

    # RSI 조건에 따라 텔레그램 알림 전송
    if nrsi_240 <= 30:    # 과매도 영역
        message = f"{symbol[4:]}, \n60분: {nrsi_60}, 240분: {nrsi_240}, 매수"
        send_telegram_message(message)
    if nrsi_240 >= 70:    # 과매수 영역
        message = f"{symbol[4:]}, \n60분: {nrsi_60}, 240분: {nrsi_240}, 매도"
        send_telegram_message(message)

# 주어진 OHLC 데이터프레임을 사용하여 RSI 값을 계산하는 함수
def rsi_calc(ohlc: pd.DataFrame, period: int = 14):
    ohlc["trad_price"] = ohlc["trade_price"]  # 거래 가격 열 복사
    delta = ohlc["trade_price"].diff()  # 연속 차이 계산
    gains, declines = delta.copy(), delta.copy()
    gains[gains < 0] = 0        # 상승폭만 남기기
    declines[declines > 0] = 0  # 하락폭만 남기기

    # 지수 이동 평균으로 평균 상승/하락 계산
    _gain = gains.ewm(com=(period-1), min_periods=period).mean()
    _loss = declines.abs().ewm(com=(period-1), min_periods=period).mean()

    RS = _gain / _loss
    return pd.Series(100-(100/(1+RS)), name="RSI")  # RSI 공식 적용


# ===================================== 삭제
# 실행부: 모든 KRW 코인에 대해 RSI 분석
# krw_coins = get_krw_coins()
# for coin in krw_coins:
#    rsi_upbit(60, coin)  # 60분 간격 RSI 체크
#    time.sleep(1)  # API 호출 간 딜레이
# ===================================== 삭제 끝

# 실행부: 모든 코인이 아닌 내가 지정한 n개 코인만 RSI 분석
selected_coins = [
    'KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-SUI','KRW-TRUMP','KRW-USDT','KRW-ATOM',
    'KRW-DOGE', 'KRW-DOT', 'KRW-AVAX', 'KRW-LINK', 'KRW-TRX','KRW-ONDO', 'KRW-JUP','KRW-ME','KRW-ASTR',
    'KRW-SEI', 'KRW-SAND', 'KRW-CTC', 'KRW-GRT', 'KRW-HBAR', 'KRW-CRO','KRW-ETC'
]

while True:   
    for coin in selected_coins:
        rsi_upbit(60, coin)  # 60분 간격 RSI 체크
        time.sleep(1)        # API 호출 간 딜레이
    print("⏳ 1시간 대기 중...")
    time.sleep(3600)         # 1시간 대기 후 다시 실행
# [수정된 부분 끝]
# ================================