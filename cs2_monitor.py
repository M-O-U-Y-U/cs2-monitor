import requests
import time
import json
import os
import datetime

# ================= 配置区域 =================
WXPUSHER_APP_TOKEN = "AT_yHKSDVeK6iT5WJO6UEgHybzBaA0dBpGa"
WXPUSHER_UID = "UID_xpTn3FaNA1yWqDvDMQJYurXEen72"
STEAM_ID = "76561199123057301"
DATA_FILE = "advanced_data.json"

MIN_ITEM_VALUE = 0.5
MIN_INCREASE_PERCENT = 0.1 
# ============================================

def send_wxpusher(title, content):
    if not WXPUSHER_APP_TOKEN or "AT_" not in WXPUSHER_APP_TOKEN: return
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": WXPUSHER_APP_TOKEN,
        "content": f"<h2>{title}</h2><br>{content}",
        "summary": title, 
        "contentType": 2, 
        "uids": [WXPUSHER_UID]
    }
    try:
        requests.post(url, json=payload)
    except: pass

def get_inventory():
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=schinese&count=500"
    items = {}
    try:
        res = requests.get(url, timeout=10).json()
        for item in res.get('descriptions', []):
            if item.get('marketable'):
                hash_name = item['market_hash_name']
                items[hash_name] = item.get('name', hash_name)
        return items
    except: return {}

def get_price(hash_name):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": hash_name}
    try:
        res = requests.get(url, params=params, timeout=10).json()
        price = res.get('lowest_price', '0').replace('¥', '').replace(',', '')
        return float(price)
    except: return 0

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    is_11_pm = (now_bj.hour == 23) 

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f: 
            db = json.load(f)
    else: 
        db = {}

    # 获取系统元数据，用于控制每日复盘只发一次
    meta = db.get("_meta", {})
    last_report_date = meta.get("last_report_date", "")
    
    # 判断当前是否需要生成晚间23点的报告
    should_generate_daily = False
    if is_11_pm and last_report_date != today_str:
        should_generate_daily = True
        meta["last_report_date"] = today_str
    
    db["_meta"] = meta

    inventory_items = get_inventory()
    hourly_alerts = []
    daily_summary = []

    for hash_name, cn_name in inventory_items.items():
        price = get_price(hash_name)
        if price < MIN_ITEM_VALUE:
            time.sleep(5)
            continue
        
        # 处理第一次出现或兼容旧版数据
        if hash_name not in db:
            db[hash_name] = {"start_price": price, "last_price": price, "history": [{"time": current_time_str, "price": price}]}
        else:
            # 兼容旧版本纯数字数组，平滑升级为时间戳对象数组
            old_history = db[hash_name].get("history", [])
            new_history = []
            for h in old_history:
                if isinstance(h, dict):
                    new_history.append(h)
                else:
                    new_history.append({"time": "历史", "price": float(h)})
            db[hash_name]["history"] = new_history
        
        item_data = db[hash_name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        
        # ========== 1. 常规涨幅监控 ==========
        if price > last_price:
            increase_percent = ((price - last_price) / last_price) * 100
            
            if increase_percent >= MIN_INCREASE_PERCENT:
                daily_ratio = ((price - start_price) / start_price * 100) if start_price > 0 else 0
                highest_so_far = max([x["price"] for x in item_data["history"]] + [start_price])
                
                high_tag = "🔥 <span style='color:red;'><b>突破今日新高</b></span>" if price > highest_so_far else "📈 价格回升 (波动期)"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b style='font-size:16px;'>{cn_name}</b><br>"
                       f"<span style='font-size:12px; color:#888;'>原名: {hash_name}</span><br>"
                       f"状态：{high_tag}<br>"
                       f"相比上次：¥{last_price:.2f} ➡️ <b>当前：¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"对比今日开盘(¥{start_price:.2f})：累计走势 <b>{daily_ratio:+.2f}%</b>"
                       f"</div>")
                hourly_alerts.append(msg)
        
        # 更新价格与时间轨迹
        item_data["history"].append({"time": current_time_str, "price": price})
        item_data["last_price"] = price
        
        # ========== 2. 晚间 23 点复盘逻辑 ==========
        if should_generate_daily:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            if abs(net_change) >= MIN_INCREASE_PERCENT:
                trend_color = "red" if net_change > 0 else "green"
                
                # 拼接带有时间节点的轨迹字符串，例如：14:17(¥1.50) > 14:47(¥1.55)
                history_str_list = [f"{x['time']}(¥{x['price']:.2f})" for x in item_data['history']]
                history_path = " > ".join(history_str_list)
                
                summary_msg = (f"<b>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"开盘 ¥{start_price:.2f} ➡️ 收盘 ¥{price:.2f} "
                               f"<span style='color:{trend_color};'>({net_change:+.2f}%)</span><br>"
                               f"<span style='font-size:12px; color:#888;'>今日轨迹: {history_path}</span>")
                daily_summary.append((net_change, summary_msg))
            
            # 复盘后重置，为第二天做准备
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]

        time.sleep(5)

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    # 发送推送
    if hourly_alerts:
        send_wxpusher(f"CS2饰品上涨通知 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<br><hr><br>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 CS2饰品今日涨跌复盘 ({today_str})", f"以下为今日产生有效波动的饰品：<br><br>{final_summary_html}")

if __name__ == "__main__":
    main()
