import os, time, requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
CHECK_INTERVAL = 300  # 5 daqiqa

def get_gold_price():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        prev  = data["chart"]["result"][0]["meta"]["previousClose"]
        high  = data["chart"]["result"][0]["meta"].get("regularMarketDayHigh", price)
        low   = data["chart"]["result"][0]["meta"].get("regularMarketDayLow", price)
        return float(price), float(prev), float(high), float(low)
    except Exception as e:
        print(f"Narx olishda xato: {e}")
        return None, None, None, None

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 2.0
    trs = []
    for i in range(1, min(len(closes), period+1)):
        hl  = highs[i] - lows[i] if i < len(highs) else 2.0
        hpc = abs(highs[i] - closes[i-1]) if i < len(highs) else 2.0
        lpc = abs(lows[i] - closes[i-1]) if i < len(lows) else 2.0
        trs.append(max(hl, hpc, lpc))
    return round(sum(trs) / len(trs), 2) if trs else 2.0

def calc_lot(balance, risk_pct, sl_dist):
    risk_amt = balance * risk_pct / 100
    # XAUUSD: 1 lot = 100 oz, pip = $0.01 => pip value = $1 per 0.01 lot
    pip_value = 1.0  # $1 per pip per 0.01 lot
    sl_pips   = sl_dist / 0.1
    lot = risk_amt / (sl_pips * pip_value * 10)
    lot = round(max(0.01, min(5.0, lot)), 2)
    return lot, round(risk_amt, 2)

def get_signal(price, prev, rsi, atr, high_day, low_day):
    change_pct = ((price - prev) / prev) * 100
    buy_score  = 0
    sell_score = 0
    reasons    = []

    # RSI
    if rsi < 35:
        buy_score += 2
        reasons.append(f"RSI={rsi} ⬇ Oversold")
    elif rsi > 65:
        sell_score += 2
        reasons.append(f"RSI={rsi} ⬆ Overbought")
    else:
        reasons.append(f"RSI={rsi} neytral")

    # Narx o'zgarishi
    if change_pct <= -0.3:
        sell_score += 1
        reasons.append(f"Narx {change_pct:.2f}% tushgan")
    elif change_pct >= 0.3:
        buy_score += 1
        reasons.append(f"Narx +{change_pct:.2f}% o'sgan")

    # Kun ichidagi pozitsiya
    day_range = high_day - low_day
    if day_range > 0:
        pos = (price - low_day) / day_range
        if pos < 0.25:
            buy_score += 1
            reasons.append("Kun pastiga yaqin")
        elif pos > 0.75:
            sell_score += 1
            reasons.append("Kun yuqorisiga yaqin")

    # Sessiya filtri (London/NY: 07-17 UTC)
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour <= 17:
        reasons.append("✅ Aktiv sessiya")
    else:
        reasons.append("⚠️ Sessiya tashqarisi")
        buy_score  = max(0, buy_score - 1)
        sell_score = max(0, sell_score - 1)

    # Qaror
    if buy_score >= 3 and buy_score > sell_score:
        return "BUY", buy_score, sell_score, reasons
    elif sell_score >= 3 and sell_score > buy_score:
        return "SELL", buy_score, sell_score, reasons
    return "KUTING", buy_score, sell_score, reasons

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram sozlanmagan!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }, timeout=10)
    return r.status_code == 200

def format_message(signal, price, prev, rsi, atr, reasons, balance=1000, risk_pct=1.0):
    change     = price - prev
    change_pct = (change / prev) * 100
    change_str = f"+{change:.2f}" if change >= 0 else f"{change:.2f}"
    time_now   = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    # SL va TP hisoblash (ATR asosida)
    sl_mult = 1.5
    tp_mult = 2.5
    sl_dist = round(atr * sl_mult, 2)
    tp_dist = round(atr * tp_mult, 2)

    if signal == "BUY":
        sl_price = round(price - sl_dist, 2)
        tp1      = round(price + tp_dist * 0.6, 2)
        tp2      = round(price + tp_dist, 2)
        tp3      = round(price + tp_dist * 1.5, 2)
        emoji    = "📈"
        sig_text = "BUY — SOTIB OL"
        direction = "⬆️"
    else:
        sl_price = round(price + sl_dist, 2)
        tp1      = round(price - tp_dist * 0.6, 2)
        tp2      = round(price - tp_dist, 2)
        tp3      = round(price - tp_dist * 1.5, 2)
        emoji    = "📉"
        sig_text = "SELL — SOT"
        direction = "⬇️"

    sl_pips = round(sl_dist / 0.1)
    tp_pips = round(tp_dist / 0.1)
    rr      = round(tp_pips / sl_pips, 1)

    lot, risk_amt = calc_lot(balance, risk_pct, sl_dist)
    margin  = round(lot * 100 * price / 100, 2)
    profit1 = round(lot * tp_pips * 0.6 * 1.0, 2)
    profit2 = round(lot * tp_pips * 1.0, 2)
    loss    = round(risk_amt, 2)

    reasons_text = "\n".join([f"  • {r}" for r in reasons])

    msg = f"""{emoji} <b>XAUUSD SIGNALI — {sig_text}</b> {direction}
🕐 <b>Vaqt:</b> {time_now} | M5
━━━━━━━━━━━━━━━━━━━━
💰 <b>Kirish narxi:</b>  <code>{price:.2f}</code>
   ({change_str} | {change_pct:+.2f}%)
━━━━━━━━━━━━━━━━━━━━
🛑 <b>Stop Loss:</b>    <code>{sl_price:.2f}</code>  (-{sl_pips} pip)
━━━━━━━━━━━━━━━━━━━━
✅ <b>Take Profit 1:</b> <code>{tp1:.2f}</code>  (+{round(tp_pips*0.6)} pip)
✅ <b>Take Profit 2:</b> <code>{tp2:.2f}</code>  (+{tp_pips} pip)
✅ <b>Take Profit 3:</b> <code>{tp3:.2f}</code>  (+{round(tp_pips*1.5)} pip)
⚖️  <b>R:R nisbat:</b>   1:{rr}
━━━━━━━━━━━━━━━━━━━━
📦 <b>Lot size:</b>     <code>{lot}</code>
🏦 <b>Marja:</b>        <code>${margin}</code>
📊 <b>Foyda (TP1):</b>  <code>+${profit1}</code>
📊 <b>Foyda (TP2):</b>  <code>+${profit2}</code>
⚠️  <b>Max zarar:</b>   <code>-${loss}</code>
━━━━━━━━━━━━━━━━━━━━
📡 <b>Sabablar:</b>
{reasons_text}
━━━━━━━━━━━━━━━━━━━━
📊 RSI: {rsi} | ATR: {atr}
<i>⚡ Exness da qo'lda oching | $1000 / 1% risk</i>"""
    return msg

# === ASOSIY TSIKL ===
price_history = []
high_history  = []
low_history   = []
last_signal   = ""

print("🚀 XAUUSD Signal Bot ishga tushdi!")
send_telegram("🚀 <b>XAUUSD Signal Bot ishga tushdi!</b>\n⏱ Har 5 daqiqada signal tekshiriladi.\n📊 SL, TP1, TP2, TP3 va Lot size beriladi.")

while True:
    try:
        price, prev, high, low = get_gold_price()

        if price and prev:
            price_history.append(price)
            high_history.append(high)
            low_history.append(low)

            if len(price_history) > 50:
                price_history = price_history[-50:]
                high_history  = high_history[-50:]
                low_history   = low_history[-50:]

            rsi = calc_rsi(price_history)
            atr = calc_atr(high_history, low_history, price_history)

            signal, buy_sc, sell_sc, reasons = get_signal(
                price, prev, rsi, atr, high, low)

            now = datetime.now(timezone.utc).strftime('%H:%M')
            print(f"[{now}] Narx: {price:.2f} | RSI: {rsi} | ATR: {atr} | Signal: {signal} (B:{buy_sc} S:{sell_sc})")

            if signal != "KUTING" and signal != last_signal:
                msg = format_message(signal, price, prev, rsi, atr, reasons)
                if send_telegram(msg):
                    print(f"✅ Telegram: {signal} signali yuborildi!")
                last_signal = signal

        time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
        break
    except Exception as e:
        print(f"Xato: {e}")
        time.sleep(60)
