import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import requests
import os
from datetime import datetime, timedelta

# ==========================================
# 1. 策略設定區域 (雙軌制 + 福懋油)
# ==========================================

# 定義原料代號
COMMODITIES = {
    "CORN": {"ticker": "ZC=F", "name": "玉米"},
    "SOY":  {"ticker": "ZS=F", "name": "黃豆"}
}

# 定義監控清單與對應原料
# 格式： "股票代號": {"name": "中文名", "target": "對應原料KEY"}
WATCH_LIST = {
    # --- A組：玉米組 (澱粉/果糖) ---
    "1220.TW": {"name": "台榮", "target": "CORN"},
    
    # --- B組：黃豆組 (飼料/肉品/油脂) ---
    "1210.TW": {"name": "大成",   "target": "SOY"},
    "1215.TW": {"name": "卜蜂",   "target": "SOY"},
    "1219.TW": {"name": "福壽",   "target": "SOY"},
    "1225.TW": {"name": "福懋油", "target": "SOY"}  # ✅ 新增這行
}

LOOKBACK_DAYS = 180
STRATEGY_WINDOW = 20
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# ==========================================
# 2. 外部資料抓取 (營收)
# ==========================================

def get_twse_revenue_data():
    print("☁️ 正在抓取最新營收資料...")
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            rev_map = {}
            # 動態尋找包含 '去年同月增減' 的欄位
            yoy_key = next((k for k in data[0].keys() if "去年同月增減" in k), None)
            if yoy_key:
                for row in data:
                    rev_map[row["公司代號"]] = float(row.get(yoy_key, "0").replace(",", ""))
            return rev_map
    except:
        pass
    return {}

def send_discord_notify(msg, img_path=None):
    if not DISCORD_WEBHOOK_URL:
        print(msg) # 本地測試直接印出
        return
    try:
        data = {"content": msg}
        files = {"file": (os.path.basename(img_path), open(img_path, "rb"))} if img_path else None
        requests.post(DISCORD_WEBHOOK_URL, data=data, files=files)
        if files: files["file"][1].close()
        print("✅ Discord 通知發送成功")
    except Exception as e:
        print(f"❌ Discord 發送錯誤: {e}")

# ==========================================
# 3. 核心邏輯
# ==========================================

def get_data():
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS + 10)).strftime('%Y-%m-%d')
    # 收集所有需要下載的代號 (原料 + 股票)
    tickers = [c["ticker"] for c in COMMODITIES.values()] + list(WATCH_LIST.keys())
    print(f"Downloading data for {len(tickers)} tickers...")
    try:
        data = yf.download(tickers, start=start_date, progress=False)['Close']
        return data.ffill()
    except Exception as e:
        print(f"❌ 下載失敗: {e}")
        return pd.DataFrame()

def analyze_stock(stock_code, stock_data, comm_data, comm_name, rev_yoy, prev_stock, prev_comm):
    # 計算變動率
    s_pct = ((stock_data.iloc[-1] - prev_stock) / prev_stock) * 100
    c_pct = ((comm_data.iloc[-1] - prev_comm) / prev_comm) * 100
    
    # 計算開口度 (Gap) - 正規化比較
    norm_stock = (stock_data / stock_data.iloc[0]) * 100
    norm_comm = (comm_data / comm_data.iloc[0]) * 100
    gap = norm_stock.iloc[-1] - norm_comm.iloc[-1]
    
    # 策略判斷
    cost_down = c_pct < 0
    rev_up = rev_yoy > 0
    
    signal = "⚖️ 觀望"
    
    if rev_up and s_pct < -5:
        signal = "📉 **預警(背離)**" # 營收好股價崩
    elif cost_down:
        if gap < -10: signal = "🎯 **黃金買點** (成本降+股價低估)"
        elif rev_up:  signal = "🚀 **雙引擎** (成本降+營收增)"
        else:         signal = "✨ **潛在轉機** (成本優勢)"
    else:
        if not rev_up: signal = "☠️ **雙殺風險**"
        
    # 格式化輸出
    res = f"> **{stock_code.split('.')[0]} {WATCH_LIST[stock_code]['name']}** ({comm_name})\n"
    res += f"> 股價 `{s_pct:+.1f}%` | 原料 `{c_pct:+.1f}%` | 營收 `{rev_yoy:+.1f}%`\n"
    res += f"> 策略: {signal} (Gap: {gap:+.1f})\n"
    return res

def plot_dual_chart(df):
    plt.figure(figsize=(12, 10)) # 加高畫布
    plt.style.use('bmh')
    
    # --- 子圖 1: 玉米組 ---
    ax1 = plt.subplot(2, 1, 1)
    comm_corn = COMMODITIES["CORN"]["ticker"]
    if comm_corn in df.columns:
        norm_corn = (df[comm_corn] / df[comm_corn].iloc[0]) * 100
        ax1.plot(norm_corn.index, norm_corn, 'r--', linewidth=2, label='Corn (Cost)')
        
        for code, info in WATCH_LIST.items():
            if info["target"] == "CORN" and code in df.columns:
                norm_s = (df[code] / df[code].iloc[0]) * 100
                ax1.plot(norm_s.index, norm_s, label=f"{info['name']}")
    
    ax1.set_title(f"Group A: Starch (vs Corn) - {LOOKBACK_DAYS} Days")
    ax1.legend()
    ax1.grid(True)

    # --- 子圖 2: 黃豆組 ---
    ax2 = plt.subplot(2, 1, 2)
    comm_soy = COMMODITIES["SOY"]["ticker"]
    if comm_soy in df.columns:
        norm_soy = (df[comm_soy] / df[comm_soy].iloc[0]) * 100
        ax2.plot(norm_soy.index, norm_soy, 'r--', linewidth=2, label='Soybean (Cost)')
        
        for code, info in WATCH_LIST.items():
            if info["target"] == "SOY" and code in df.columns:
                norm_s = (df[code] / df[code].iloc[0]) * 100
                ax2.plot(norm_s.index, norm_s, label=f"{info['name']}")
            
    ax2.set_title(f"Group B: Feed & Oil (vs Soybean) - {LOOKBACK_DAYS} Days")
    ax2.legend()
    ax2.grid(True)
    
    plt.tight_layout()
    img_path = "dual_monitor_chart.png"
    plt.savefig(img_path)
    plt.close()
    return img_path

# ==========================================
# 4. 主程式
# ==========================================

def main():
    df = get_data()
    if df.empty: return
    rev_data = get_twse_revenue_data()
    img_path = plot_dual_chart(df)
    
    date_str = df.index[-1].strftime('%Y-%m-%d')
    msg = f"**【食品股 原料雙軌監控系統】**\n📅 `{date_str}`\n\n"
    
    # 計算基準點
    try:
        prev_idx = -STRATEGY_WINDOW
        df.iloc[prev_idx] # check exist
    except:
        prev_idx = 0
        
    # 分組報告
    groups = {"CORN": "🌽 **澱粉組 (對比玉米)**", "SOY": "🥜 **飼料油脂組 (對比黃豆)**"}
    
    for target_key, group_title in groups.items():
        msg += f"{group_title}\n"
        comm_ticker = COMMODITIES[target_key]["ticker"]
        comm_name = COMMODITIES[target_key]["name"]
        
        if comm_ticker not in df.columns: continue

        # 該原料漲跌
        c_now = df[comm_ticker].iloc[-1]
        c_prev = df[comm_ticker].iloc[prev_idx]
        
        for code, info in WATCH_LIST.items():
            if info["target"] == target_key and code in df.columns:
                rev = rev_data.get(code.split('.')[0], 0.0)
                msg += analyze_stock(
                    code, df[code], df[comm_ticker], comm_name, rev,
                    df[code].iloc[prev_idx], c_prev
                )
        msg += "\n"

    msg += "💡 **操作備忘：**\nGap < -10 (股價落後原料跌幅) 為價值買點。\n"
    msg += "台榮看玉米，飼料與福懋油看黃豆，精準分組。"
    
    send_discord_notify(msg, img_path)
    print("Done.")

if __name__ == "__main__":
    main()
