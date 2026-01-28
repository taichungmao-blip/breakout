import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import requests
import os
from datetime import datetime, timedelta

# ==========================================
# 1. 終極字型解決方案 (強制下載並指定路徑)
# ==========================================

def get_chinese_font():
    """
    直接下載並回傳字型物件，不依賴系統安裝
    """
    font_name = "NotoSansTC-Regular.ttf"
    # 使用 Google Fonts 的穩定連結
    font_url = "https://github.com/google/fonts/raw/main/ofl/notosanstc/NotoSansTC-Regular.ttf"
    
    # 1. 檢查檔案是否存在，不存在就下載
    if not os.path.exists(font_name):
        print(f"📥 正在下載中文字型檔 ({font_name})...")
        try:
            response = requests.get(font_url)
            with open(font_name, 'wb') as f:
                f.write(response.content)
            print("✅ 字型下載完成！")
        except Exception as e:
            print(f"❌ 字型下載失敗，將無法顯示中文: {e}")
            return None
            
    # 2. 直接建立字型物件 (Bypass 系統設定)
    return fm.FontProperties(fname=font_name)

# ==========================================
# 2. 策略參數設定
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
# 3. 資料處理函式
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
            # 精準鎖定「去年同月增減」
            if data:
                keys = list(data[0].keys())
                yoy_key = next((k for k in keys if "增減" in k and "去年" in k and "上月" not in k), None)
                if yoy_key:
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
        print(f"❌ 營收抓取錯誤: {e}")
    return {}

def get_data():
    start = (datetime.now() - timedelta(days=LOOKBACK_DAYS + 10)).strftime('%Y-%m-%d')
    tickers = [c["ticker"] for c in COMMODITIES.values()] + list(WATCH_LIST.keys())
    print(f"📥 下載股價數據中 ({len(tickers)} 檔)...")
    try:
        data = yf.download(tickers, start=start, progress=False)['Close']
        return data.ffill() if not data.empty else pd.DataFrame()
    except Exception as e:
        print(f"❌ yfinance 下載失敗: {e}")
        return pd.DataFrame()

def send_discord_notify(msg, img_path=None):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ 未設定 Webhook，跳過發送。")
        print(msg)
        return
    try:
        data = {"content": msg}
        files = {"file": (os.path.basename(img_path), open(img_path, "rb"))} if img_path else None
        requests.post(DISCORD_WEBHOOK_URL, data=data, files=files)
        if files: files["file"][1].close()
        print("✅ Discord 通知發送成功")
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")

def analyze_stock(stock_code, stock_data, comm_data, comm_name, rev_yoy, prev_stock, prev_comm):
    s_pct = ((stock_data.iloc[-1] - prev_stock) / prev_stock) * 100
    c_pct = ((comm_data.iloc[-1] - prev_comm) / prev_comm) * 100
    gap = (stock_data / stock_data.iloc[0] * 100).iloc[-1] - (comm_data / comm_data.iloc[0] * 100).iloc[-1]
    spread = rev_yoy - c_pct
    
    signal = "⚖️ 觀望"
    icon = "⚪"
    
    if spread > 10: 
        if gap < -5: signal = "💎 **鑽石買點**"; icon = "💎"
        else: signal = "🔥 **強勢成長**"; icon = "🔥"
    elif spread > 0:
        if gap < -10: signal = "🎯 **黃金買點**"; icon = "🎯"
        else: signal = "✅ **穩健持有**"; icon = "✅"
    else: 
        if s_pct < -5: signal = "📉 **弱勢盤整**"; icon = "📉"
        else: signal = "⚠️ **獲利壓縮**"; icon = "⚠️"

    cost_status = "↘(利多)" if c_pct < 0 else "↗(利空)"
    name = WATCH_LIST[stock_code]['name']
    
    res = f"> {icon} **{stock_code.split('.')[0]} {name}** (對比{comm_name})\n"
    res += f"> 剪刀差 `{spread:+.1f}` | 營收 `{rev_yoy:+.1f}%` | 成本 {cost_status} `{c_pct:+.1f}%`\n"
    res += f"> 股價 `{s_pct:+.1f}%` | Gap `{gap:+.1f}` | 評級: {signal}\n"
    return res

# ==========================================
# 4. 繪圖核心 (強制套用字型物件)
# ==========================================

def plot_dual_chart(df):
    # 取得字型物件 (關鍵！)
    my_font = get_chinese_font()
    
    plt.figure(figsize=(12, 12))
    plt.style.use('bmh')
    
    # --- 子圖1: 玉米組 ---
    ax1 = plt.subplot(2, 1, 1)
    if COMMODITIES["CORN"]["ticker"] in df.columns:
        c_tick = COMMODITIES["CORN"]["ticker"]
        norm_c = (df[c_tick] / df[c_tick].iloc[0]) * 100
        ax1.plot(norm_c.index, norm_c, 'r--', lw=3, label='原料: 玉米 (Corn)')
        
        for k, v in WATCH_LIST.items():
            if v["target"] == "CORN" and k in df.columns:
                norm_s = (df[k] / df[k].iloc[0]) * 100
                label_str = f"{k.split('.')[0]} {v['name']}"
                ax1.plot(norm_s.index, norm_s, lw=2, label=label_str)
                
    # 強制指定標題字型
    ax1.set_title(f"A組: 澱粉與果糖 (對比玉米) - 近 {LOOKBACK_DAYS} 日走勢", fontproperties=my_font, fontsize=14)
    # 強制指定圖例字型 (prop=my_font)
    ax1.legend(loc="upper left", prop=my_font)
    ax1.grid(True)

    # --- 子圖2: 黃豆組 ---
    ax2 = plt.subplot(2, 1, 2)
    if COMMODITIES["SOY"]["ticker"] in df.columns:
        s_tick = COMMODITIES["SOY"]["ticker"]
        norm_s = (df[s_tick] / df[s_tick].iloc[0]) * 100
        ax2.plot(norm_s.index, norm_s, 'r--', lw=3, label='原料: 黃豆 (Soybean)')
        
        for k, v in WATCH_LIST.items():
            if v["target"] == "SOY" and k in df.columns:
                norm_stock = (df[k] / df[k].iloc[0]) * 100
                label_str = f"{k.split('.')[0]} {v['name']}"
                ax2.plot(norm_stock.index, norm_stock, lw=2, label=label_str)
                
    # 強制指定標題字型
    ax2.set_title(f"B組: 飼料與油脂 (對比黃豆) - 近 {LOOKBACK_DAYS} 日走勢", fontproperties=my_font, fontsize=14)
    # 強制指定圖例字型
    ax2.legend(loc="upper left", prop=my_font)
    ax2.grid(True)
    
    plt.tight_layout()
    path = "v6_3_chart.png"
    plt.savefig(path)
    plt.close()
    return path

# ==========================================
# 5. 主程式
# ==========================================

def main():
    print("🚀 啟動 V6.3 終極字型修正版...")
    df = get_data()
    if df.empty: return

    rev_map = get_twse_revenue_data()
    img = plot_dual_chart(df)
    
    date = df.index[-1].strftime('%Y-%m-%d')
    msg = f"**【食品股 剪刀差獲利模型 V6.3】**\n📅 `{date}`\n"
    msg += "指標說明：\n✂️ **剪刀差 (Spread)** = 營收成長 - 成本漲幅\n(正值代表毛利擴張，台榮看玉米，其餘看黃豆)\n\n"
    
    prev_idx = -STRATEGY_WINDOW if len(df) > STRATEGY_WINDOW else 0
    groups = {"CORN": "🌽 **澱粉組 (Cost: 玉米)**", "SOY": "🥜 **飼料油脂組 (Cost: 黃豆)**"}
    
    for key, title in groups.items():
        msg += f"{title}\n"
        c_tick = COMMODITIES[key]["ticker"]
        c_name = COMMODITIES[key]["name"]
        if c_tick not in df.columns: continue
        
        c_prev = df[c_tick].iloc[prev_idx]
        for k, v in WATCH_LIST.items():
            if v["target"] == key and k in df.columns:
                rev = rev_map.get(k.split('.')[0], 0.0)
                msg += analyze_stock(k, df[k], df[c_tick], c_name, rev, df[k].iloc[prev_idx], c_prev)
        msg += "\n"
        
    send_discord_notify(msg, img)
    print("Done. 監控完成。")

if __name__ == "__main__":
    main()
