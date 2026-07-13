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

MIN_ITEM_VALUE = 0.5      # 忽略低于0.5元的物品
MIN_INCREASE_PERCENT = 1.0 # 涨幅超过1%才进行日内推送通知
# ============================================

# 初始化带伪装头的 Session，大幅降低 429 限流概率
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://steamcommunity.com/market/"
})

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
        session.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[错误] WxPusher 推送失败: {e}")

def get_inventory():
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=schinese&count=500"
    items = {}
    try:
        res = session.get(url, timeout=10)
        if res.status_code == 429:
            print("[警告] 获取库存被 Steam 限流 (429 Too Many Requests)")
            return {}
            
        data = res.json()
        for item in data.get('descriptions', []):
            if item.get('marketable'):
                hash_name = item['market_hash_name']
                items[hash_name] = item.get('name', hash_name)
        return items
    except Exception as e: 
        print(f"[错误] 获取库存失败: {e}")
        return {}

def get_market_data(hash_name):
    """获取更丰富的市场数据，包括当前最低价、日均中位价、成交量"""
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": hash_name}
    result = {"price": -1, "volume": "未知", "median": "未知"}
    try:
        res = session.get(url, params=params, timeout=10)
        if res.status_code == 429:
            print(f"[警告] 获取 {hash_name} 数据被限流 (429)")
            return result
            
        data = res.json()
        if not data.get("success"):
            return result
            
        # 提取最低在售价格
        if "lowest_price" in data:
            price_str = data['lowest_price'].replace('¥', '').replace(',', '').strip()
            result["price"] = float(price_str)
        
        # 提取24小时成交量
        if "volume" in data:
            result["volume"] = data['volume']
            
        # 提取近期历史中位价 (反映真实成交水平，防止有价无市)
        if "median_price" in data:
            result["median"] = data['median_price']
            
        return result
    except Exception as e: 
        print(f"[错误] 获取 {hash_name} 数据异常: {e}")
        return result

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    is_11_pm = (now_bj.hour >= 22) # 只要是晚上22点之后（含23点），均可视为可出夜间报告

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f: 
            db = json.load(f)
    else: 
        db = {}

    meta = db.get("_meta", {})
    last_report_date = meta.get("last_report_date", "")
    
    should_generate_daily = (is_11_pm and last_report_date != today_str)
    if should_generate_daily:
        meta["last_report_date"] = today_str
    
    db["_meta"] = meta

    inventory_items = get_inventory()
    if not inventory_items:
        print("[提示] 未获取到有效库存，脚本退出。")
        return

    hourly_alerts = []
    daily_summary = []

    for hash_name, cn_name in inventory_items.items():
        market_data = get_market_data(hash_name)
        price = market_data["price"]
        volume = market_data["volume"]
        median = market_data["median"]
        
        # 如果价格获取失败(-1)或者低于下限(0.5)，跳过常规通知，但不跳过晚间重置
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and hash_name in db:
                db[hash_name]["start_price"] = db[hash_name].get("last_price", 0)
                db[hash_name]["history"] = [{"time": "昨日收盘", "price": db[hash_name]["start_price"]}]
            time.sleep(4)
            continue
        
        # 初始化数据
        if hash_name not in db:
            db[hash_name] = {"start_price": price, "last_price": price, "history": [{"time": current_time_str, "price": price}]}
        else:
            # 兼容旧版本数据
            old_history = db[hash_name].get("history", [])
            new_history = [h if isinstance(h, dict) else {"time": "历史", "price": float(h)} for h in old_history]
            db[hash_name]["history"] = new_history
        
        item_data = db[hash_name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        
        # ========== 1. 常规涨跌幅监控 (日内实时通知) ==========
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
                       f"价格变动：¥{last_price:.2f} ➡️ <b>最低挂单：¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"<span style='font-size:12px; color:#555;'>"
                       f"24h成交量：{volume} 笔 | 参考中位价：{median}<br>"
                       f"对比今日开盘 (¥{start_price:.2f})：累计走势 <b>{daily_ratio:+.2f}%</b>"
                       f"</span></div>")
                hourly_alerts.append(msg)
        
        # 只要价格有真实变动，就记录下来保留全天轨迹
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 2. 晚间复盘逻辑 (高低点统计 + 轨迹) ==========
        if should_generate_daily:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            if abs(net_change) >= MIN_INCREASE_PERCENT or len(item_data['history']) > 1: # 只要今天涨跌超过阈值或者发生过波动，就复盘
                trend_color = "red" if net_change > 0 else "green"
                
                # 计算今日盘中最高价和最低价
                all_prices_today = [x['price'] for x in item_data['history']] + [start_price, price]
                day_high = max(all_prices_today)
                day_low = min(all_prices_today)
                
                # 拼接带有时间节点的轨迹字符串（满足你保留全天轨迹的需求）
                history_str_list = [f"{x['time']}(¥{x['price']:.2f})" for x in item_data['history']]
                history_path = " > ".join(history_str_list)
                
                summary_msg = (f"<b>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"开盘 ¥{start_price:.2f} ➡️ 收盘 <b>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span><br>"
                               f"📊 今日最高: ¥{day_high:.2f} | 今日最低: ¥{day_low:.2f}<br>"
                               f"🔥 24h热度: {volume} 笔成交 | 中位价: {median}<br>"
                               f"<div style='font-size:11px; color:#888; margin-top:4px; padding:4px; background:#f5f5f5; border-radius:4px;'>"
                               f"全天轨迹: {history_path}</div>")
                daily_summary.append((net_change, summary_msg))
            
            # 复盘后重置，为第二天做准备
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]

        time.sleep(4) # 休眠防封

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    # 发送推送
    if hourly_alerts:
        send_wxpusher(f"📈 CS2饰品异动通知 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<br><hr><br>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 CS2饰品今日大盘复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

if __name__ == "__main__":
    main()
