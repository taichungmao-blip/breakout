import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import requests
import os
import platform # 新增：用於偵測作業系統
from datetime import datetime, timedelta

# ==========================================
# 1. 策略設定區域
# ==========================================

COMMODITIES = {
    "CORN": {"ticker": "ZC=F", "name": "玉米"},
    "SOY":  {"ticker": "ZS=F", "name": "黃豆"}
}

WATCH_LIST = {
    "1220.TW": {"name": "台榮", "target": "CORN"},
    "1210.TW": {"name": "大成",   "target": "SOY"},
    "1215.TW": {"name": "卜蜂",   "target": "SOY"},
    "1219.TW": {"name": "福壽",   "target": "SOY"},
    "1225.TW": {"name": "福懋油", "target": "SOY"}
}

LOOKBACK_DAYS = 180
STRATEGY_WINDOW = 20
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# ==========================================
# 2. 資料抓取 (營收 YoY)
# ==========================================

def get_twse_revenue_data():
    print("☁️ 正在抓取最新營收資料...")
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            rev_map = {}
            keys = list(data[0].keys())
            
            # 精準鎖定「去年同月」增減
            yoy_key = None
            for k in keys:
                if "增減" in k and "去年" in k and "上月" not in k:
                    yoy_key = k
                    break
            
            if yoy_key:
                print(f"✅ 鎖定欄位: {yoy_key}")
                for row in data:
                    raw = row.get(yoy_key)
                    val = 0.0
                    if raw:
                        try:
                            clean = str(raw).replace(",", "").replace("%", "").strip()
                            if clean and clean != "-": val = float(clean)
                        except: pass
                    rev_map[row.get("公司代號")] = val
            return rev_map
    except Exception as e:
        print(f"❌ Error: {e}")
    return {}

def send_discord_notify(msg, img_path=None):
    if not DISCORD_WEBHOOK_URL:
        print(msg)
        return
    try:
        data = {"content": msg}
        files = {"file": (os.path.basename(img_path), open(img_path, "rb"))} if img_path else None
        requests.post(DISCORD_WEBHOOK_URL, data=data, files=files)
        if files: files["file"][1].close()
        print("✅ Discord sent.")
    except Exception as e:
        print(f"❌ Discord error: {e}")

# ==========================================
# 3. 核心邏輯 (含圖表字型修正)
# ==========================================

def get_data():
    start = (datetime.now() - timedelta(days=LOOKBACK_DAYS + 10)).strftime('%Y-%m-%d')
    tickers = [c["ticker"] for c in COMMODITIES.values()] + list(WATCH_LIST.keys())
    print(f"Downloading data for {len(tickers)} tickers...")
    try:
        data = yf.download(tickers, start=start, progress=False)['Close']
        return data.ffill() if not data.empty else pd.DataFrame()
    except: return pd.DataFrame()

def analyze_stock(stock_code, stock_data, comm_data, comm_name, rev_yoy, prev_stock, prev_comm):
    # 1. 基礎數據
    s_pct = ((stock_data.iloc[-1] - prev_stock) / prev_stock) * 100
    c_pct = ((comm_data.iloc[-1] - prev_comm) / prev_comm) * 100
    
    # 2. 開口度 (Gap)
    norm_stock = (stock_data / stock_data.iloc[0]) * 100
    norm_comm = (comm_data / comm_data.iloc[0]) * 100
    gap = norm_stock.iloc[-1] - norm_comm.iloc[-1]
    
    # 3. 剪刀差 (Spread)
    spread = rev_yoy - c_pct
    
    # --- 綜合策略 ---
    signal = "⚖️ 觀望"
    icon = "⚪"
    
    if spread > 10:
        if gap < -5:
            signal = "💎 **鑽石買點** (獲利爆發+股價低估)"
            icon = "💎"
        else:
            signal = "🔥 **強勢成長** (獲利擴張中)"
            icon = "🔥"
    elif spread > 0:
        if gap < -10:
            signal = "🎯 **黃金買點** (成本降+股價委屈)"
            icon = "🎯"
        else:
            signal = "✅ **穩健持有** (能夠轉嫁成本)"
            icon = "✅"
    else:
        if s_pct < -5:
            signal = "📉 **弱勢盤整** (基本面轉弱)"
            icon = "📉"
        else:
            signal = "⚠️ **獲利壓縮** (營收跟不上成本)"
            icon = "⚠️"

    name = WATCH_LIST[stock_code]['name']
    res = f"> {icon} **{stock_code.split('.')[0]} {name}** ({comm_name})\n"
    res += f"> 剪刀差 `{spread:+.1f}` (營收 `{rev_yoy:+.1f}%` - 原料 `{c_pct:+.1f}%`)\n"
    res += f"> 股價 `{s_pct:+.1f}%` | Gap `{gap:+.1f}`\n"
    res += f"> 評級: {signal}\n"
    return res

# 🔧 新增：設定中文字型功能
def set_chinese_font():
    """
    根據作業系統自動設定 Matplotlib 的中文字型
    """
    system = platform.system()
    if system == 'Windows':
        # Windows 預設使用微軟正黑體
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei'] 
    elif system == 'Darwin': 
        # Mac OS 使用 Arial Unicode MS 或 Heiti TC
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Heiti TC']
    else:
        # Linux / Colab 環境通常需要手動安裝字型，這裡設定常見的免費字型
        plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'Droid Sans Fallback']
    
    # 讓負號正常顯示 (不要變成方框)
    plt.rcParams['axes.unicode_minus'] = False

def plot_dual_chart(df):
    set_chinese_font() # ✅ 在繪圖前呼叫字型設定
    
    plt.figure(figsize=(12, 10))
    plt.style.use('bmh')
    
    # 子圖1: 玉米
    ax1 = plt.subplot(2, 1, 1)
    if COMMODITIES["CORN"]["ticker"] in df.columns:
        c_tick = COMMODITIES["CORN"]["ticker"]
        norm_c = (df[c_tick]/df[c_tick].iloc[0])*100
        ax1.plot(norm_c.index, norm_c, 'r--', lw=2, label='Corn Cost')
        for k,v in WATCH_LIST.items():
            if v["target"]=="CORN" and k in df.columns:
                # 修正標籤：加入代號 "1220 台榮"
                label_str = f"{k.split('.')[0]} {v['name']}"
                ax1.plot((df[k]/df[k].iloc[0])*100, label=label_str)
                
    ax1.set_title(f"Corn Group (Starch) - {LOOKBACK_DAYS} Days"); ax1.legend(); ax1.grid(True)

    # 子圖2: 黃豆
    ax2 = plt.subplot(2, 1, 2)
    if COMMODITIES["SOY"]["ticker"] in df.columns:
        s_tick = COMMODITIES["SOY"]["ticker"]
        norm_s = (df[s_tick]/df[s_tick].iloc[0])*100
        ax2.plot(norm_s.index, norm_s, 'r--', lw=2, label='Soy Cost')
        for k,v in WATCH_LIST.items():
            if v["target"]=="SOY" and k in df.columns:
                # 修正標籤：加入代號 "1210 大成"
                label_str = f"{k.split('.')[0]} {v['name']}"
                ax2.plot((df[k]/df[k].iloc[0])*100, label=label_str)
                
    ax2.set_title(f"Soybean Group (Feed/Oil) - {LOOKBACK_DAYS} Days"); ax2.legend(); ax2.grid(True)
    
    plt.tight_layout()
    path = "v6_chart.png"
    plt.savefig(path)
    plt.close()
    return path

# ==========================================
# 4. 主程式
# ==========================================

def main():
    df = get_data()
    if df.empty: return
    rev_map = get_twse_revenue_data()
    img = plot_dual_chart(df)
    
    date = df.index[-1].strftime('%Y-%m-%d')
    msg = f"**【食品股 剪刀差獲利模型 V6.1】**\n📅 `{date}`\n"
    msg += "指標說明：\n✂️ **剪刀差 (Spread)** = 營收成長 - 成本漲幅\n(數值越大代表毛利擴張能力越強)\n\n"
    
    prev_idx = -STRATEGY_WINDOW if len(df) > STRATEGY_WINDOW else 0
    
    groups = {"CORN": "🌽 **澱粉組**", "SOY": "🥜 **飼料油脂組**"}
    for key, title in groups.items():
        msg += f"{title}\n"
        c_tick = COMMODITIES[key]["ticker"]
        if c_tick not in df.columns: continue
        
        c_prev = df[c_tick].iloc[prev_idx]
        for k, v in WATCH_LIST.items():
            if v["target"] == key and k in df.columns:
                rev = rev_map.get(k.split('.')[0], 0.0)
                msg += analyze_stock(k, df[k], df[c_tick], v["name"], rev, 
                                   df[k].iloc[prev_idx], c_prev)
        msg += "\n"
        
    send_discord_notify(msg, img)
    print("Done.")

if __name__ == "__main__":
    main()
