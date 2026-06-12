import os, time, requests
from datetime import datetime

# === SOZLAMALAR ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
CHECK_INTERVAL = 300  # 5 daqiqa (soniya)

def get_gold_price():
    """Yahoo Finance dan XAUUSD narxini olish"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        prev  = data["chart"]["result"][0]["meta"]["previousClose"]
        return float(price), float(prev)
    except:
        return None, None

def calc_rsi(prices, period=14):
    """RSI hisoblash"""
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

def get_signal(price, prev_price, rsi):
    """Signal aniqlash"""
    change_pct = ((price - prev_price) / prev_price) * 100

    score_buy  = 0
    score_sell = 0
    reasons    = []

    # RSI
    if rsi < 35:
        score_buy += 2
        reasons.append(f"RSI={rsi} (oversold)")
    elif rsi > 65:
        score_sell += 2
        reasons.append(f"RSI={rsi} (overbought)")
    else:
        reasons.append(f"RSI={rsi} (neytral)")

    # Narx o'zgarishi
    if change_pct < -0.3:
        score_sell += 1
        reasons.append(f"Narx -{abs(change_pct):.2f}% tushgan")
    elif change_pct > 0.3:
        score_buy += 1
        reasons.append(f"Narx +{change_pct:.2f}% o'sgan")

    # Vaqt filtri (Lonon/NY sessiya)
    hour = datetime.utcnow().hour
    if 7 <= hour <= 17:
        score_buy  += 1
        score_sell += 1
        reasons.append("Aktiv sessiya (07-17 UTC)")
    else:
        reasons.append("⚠️ Sessiya tashqarisida")

    # Qaror
    if score_buy >= 3:
        signal = "BUY"
    elif score_sell >= 3:
        signal = "SELL"
    else:
        signal = "KUTING"

    return signal, score_buy, score_sell, reasons

def calc_lot(balance, risk_pct, sl_pips):
    """Lot hisoblash"""
    risk_amt = balance * risk_pct / 100
    pip_val  = 10  # XAUUSD 1 pip = $10 (1 lot)
    lot = risk_amt / (sl_pips * pip_val)
    return round(max(0.01, min(5.0, lot)), 2)

def send_telegram(message):
    """Telegram xabar yuborish"""
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

def format_signal_message(signal, price, prev, rsi, reasons):
    """Signal xabarini formatlash"""
    change     = price - prev
    change_pct = (change / prev) * 100
    change_str = f"+{change:.2f}" if change >= 0 else f"{change:.2f}"

    # SL/TP hisoblash
    sl_pips = 25
    tp_pips = 40
    if signal == "BUY":
        sl_price = round(price - sl_pips * 0.1, 2)
        tp_price = round(price + tp_pips * 0.1, 2)
        emoji    = "📈"
        sig_text = "BUY (SOTIB OL)"
    elif signal == "SELL":
        sl_price = round(price + sl_pips * 0.1, 2)
        tp_price = round(price - tp_pips * 0.1, 2)
        emoji    = "📉"
        sig_text = "SELL (SOT)"
    else:
        sl_price = round(price - sl_pips * 0.1, 2)
        tp_price = round(price + tp_pips * 0.1, 2)
        emoji    = "⏸"
        sig_text = "KUTING"

    # Lot (demo: $1000 balans, 1% risk)
    lot    = calc_lot(1000, 1.0, sl_pips)
    margin = round(lot * 100 * price / 100, 2)
    profit = round(lot * tp_pips * 10, 2)
    loss   = round(lot * sl_pips * 10, 2)

    reasons_text = "\n".join([f"  • {r}" for r in reasons])
    time_now     = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")

    msg = f"""{emoji} <b>XAUUSD SIGNALI — {sig_text}</b>
🕐 <b>Vaqt:</b> {time_now}
━━━━━━━━━━━━━━━━━━━━
💰 <b>Narx:</b>   <code>{price:.2f}</code>  ({change_str}, {change_pct:.2f}%)
🛑 <b>SL:</b>     <code>{sl_price:.2f}</code>  (-{sl_pips} pip)
✅ <b>TP:</b>     <code>{tp_price:.2f}</code>  (+{tp_pips} pip)
⚖️  <b>R:R:</b>   1:{round(tp_pips/sl_pips, 1)}
━━━━━━━━━━━━━━━━━━━━
📦 <b>Lot:</b>    <code>{lot}</code>  ($1000 / 1% risk)
🏦 <b>Marja:</b>  <code>${margin}</code>
📊 <b>Foyda:</b>  <code>+${profit}</code>
⚠️  <b>Zarar:</b>  <code>-${loss}</code>
━━━━━━━━━━━━━━━━━━━━
📡 <b>Sabablar:</b>
{reasons_text}
━━━━━━━━━━━━━━━━━━━━
<i>⚡ Avtomatik signal | Exness da qo'lda oching</i>"""
    return msg

# === ASOSIY TSIKL ===
last_signal   = ""
price_history = []

print("🚀 XAUUSD Signal Bot ishga tushdi!")
send_telegram("🚀 <b>XAUUSD Signal Bot ishga tushdi!</b>\n⏱ Har 5 daqiqada signal tekshiriladi.")

while True:
    try:
        price, prev = get_gold_price()

        if price and prev:
            price_history.append(price)
            if len(price_history) > 50:
                price_history = price_history[-50:]

            rsi = calc_rsi(price_history)
            signal, buy_score, sell_score, reasons = get_signal(price, prev, rsi)

            print(f"[{datetime.utcnow().strftime('%H:%M')}] Narx: {price:.2f} | RSI: {rsi} | Signal: {signal}")

            # Faqat signal o'zgarganda yuborish
            if signal != "KUTING" and signal != last_signal:
                msg = format_signal_message(signal, price, prev, rsi, reasons)
                if send_telegram(msg):
                    print(f"✅ Telegram ga yuborildi: {signal}")
                last_signal = signal

        time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
        break
    except Exception as e:
        print(f"Xato: {e}")
        time.sleep(60)
