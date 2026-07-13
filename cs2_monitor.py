import requests
import time
import json
import os
import datetime
import urllib.parse

# ================= 配置区域 =================
WXPUSHER_APP_TOKEN = "AT_yHKSDVeK6iT5WJO6UEgHybzBaA0dBpGa"
WXPUSHER_UID = "UID_xpTn3FaNA1yWqDvDMQJYurXEen72"
STEAM_ID = "76561199123057301"
DATA_FILE = "advanced_data.json"

MIN_ITEM_VALUE = 0.5       # 忽略低于0.5元的物品
MIN_INCREASE_PERCENT = 1.0 # 涨幅超过1%才进行日内推送通知
# ============================================

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
            print("[警告] 获取库存被 Steam 限流 (429)")
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
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": hash_name}
    result = {"price": -1, "volume": "未知", "median": "未知"}
    try:
        res = session.get(url, params=params, timeout=10)
        if res.status_code == 429:
            print(f"[警告] 获取 {hash_name} 数据被限流 (429)")
            return result
        data = res.json()
        if not data.get("success"): return result
            
        if "lowest_price" in data:
            result["price"] = float(data['lowest_price'].replace('¥', '').replace(',', '').strip())
        if "volume" in data:
            result["volume"] = data['volume']
        if "median_price" in data:
            result["median"] = data['median_price']
        return result
    except Exception as e: 
        print(f"[错误] 获取 {hash_name} 数据异常: {e}")
        return result

def generate_sparkline_url(prices, is_red):
    """
    通过 QuickChart API 生成微型折线图 (Sparkline) 的 URL。
    完全由前端渲染图片，不耗费服务器资源。
    """
    if not prices: return ""
    if len(prices) == 1: prices.append(prices[0]) # 如果只有一个点，复制一个画出平直线
    
    # 涨为红色，跌为绿色（匹配国内外习惯，涨红跌绿）
    color = "rgb(255, 77, 79)" if is_red else "rgb(82, 196, 26)"
    bg_color = "rgba(255, 77, 79, 0.1)" if is_red else "rgba(82, 196, 26, 0.1)"
    
    prices_str = ",".join(map(str, prices))
    # 构造 QuickChart 的 JSON 配置
    config_str = (
        f"{{type:'sparkline',data:{{datasets:[{{"
        f"data:[{prices_str}],fill:true,backgroundColor:'{bg_color}',"
        f"borderColor:'{color}',borderWidth:2,pointRadius:0"
        f"}}]}}}}"
    )
    # URL 编码并限制图片大小为 300x80
    encoded_config = urllib.parse.quote(config_str)
    return f"https://quickchart.io/chart?w=300&h=80&bkg=white&c={encoded_config}"

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    is_11_pm = (now_bj.hour >= 22)

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f: db = json.load(f)
    else: db = {}

    meta = db.get("_meta", {})
    last_report_date = meta.get("last_report_date", "")
    should_generate_daily = (is_11_pm and last_report_date != today_str)
    if should_generate_daily: meta["last_report_date"] = today_str
    db["_meta"] = meta

    inventory_items = get_inventory()
    if not inventory_items: return

    hourly_alerts = []
    daily_summary = []

    for hash_name, cn_name in inventory_items.items():
        market_data = get_market_data(hash_name)
        price = market_data["price"]
        volume = market_data["volume"]
        median = market_data["median"]
        
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and hash_name in db:
                db[hash_name]["start_price"] = db[hash_name].get("last_price", 0)
                db[hash_name]["history"] = [{"time": "昨日收盘", "price": db[hash_name]["start_price"]}]
            time.sleep(4)
            continue
        
        # 初始化及平滑升级兼容
        if hash_name not in db:
            db[hash_name] = {
                "start_price": price, 
                "last_price": price, 
                "history": [{"time": current_time_str, "price": price}],
                "historical_high": price # 【新增】记录历史最高价
            }
        else:
            old_history = db[hash_name].get("history", [])
            db[hash_name]["history"] = [h if isinstance(h, dict) else {"time": "历史", "price": float(h)} for h in old_history]
            # 兼容旧数据：如果没有 historical_high 字段，则初始化
            if "historical_high" not in db[hash_name]:
                highest_past = max([x["price"] for x in db[hash_name]["history"]] + [db[hash_name].get("start_price", price)])
                db[hash_name]["historical_high"] = highest_past
                
        item_data = db[hash_name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        historical_high = item_data["historical_high"]
        
        # ========== 1. 常规涨跌幅监控 ==========
        if price > last_price:
            increase_percent = ((price - last_price) / last_price) * 100
            if increase_percent >= MIN_INCREASE_PERCENT:
                daily_ratio = ((price - start_price) / start_price * 100) if start_price > 0 else 0
                
                # 如果当前价格突破了记录中的历史最高价，则动态更新
                if price > historical_high:
                    high_tag = "🚀 <span style='color:red;'><b>突破历史新高！</b></span>"
                    item_data["historical_high"] = price # 实时更新历史最高点
                else:
                    high_tag = "📈 价格回升 (波动期)"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b style='font-size:16px;'>{cn_name}</b><br>"
                       f"状态：{high_tag}<br>"
                       f"价格变动：¥{last_price:.2f} ➡️ <b>¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"<span style='font-size:12px; color:#555;'>"
                       f"24h热度：{volume} 笔 | 中位价：{median}<br>"
                       f"</span></div>")
                hourly_alerts.append(msg)
        
        # 记录真实波动的轨迹
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 2. 晚间复盘逻辑 (走势图 + 历史记录测算) ==========
        if should_generate_daily:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            
            if abs(net_change) >= MIN_INCREASE_PERCENT or len(item_data['history']) > 1:
                trend_color = "red" if net_change > 0 else "green"
                is_red_chart = (net_change >= 0)
                
                # 盘点今日高低价
                all_prices_today = [start_price] + [x['price'] for x in item_data['history']]
                if price not in all_prices_today: all_prices_today.append(price) # 确保最新价格在内
                
                day_high = max(all_prices_today)
                day_low = min(all_prices_today)
                
                # 生成折线图 URL
                chart_url = generate_sparkline_url(all_prices_today, is_red_chart)
                
                # 处理历史最高价逻辑
                if day_high > historical_high:
                    high_str = f"<span style='color:red;'><b>突破历史新高 (原¥{historical_high:.2f})！🎊</b></span>"
                    item_data["historical_high"] = day_high # 收盘时再次确保最高价被保存
                else:
                    high_str = f"距历史高位(¥{historical_high:.2f})差 ¥{(historical_high - day_high):.2f}"

                # 轨迹字符串
                history_str_list = [f"{x['time']}(¥{x['price']:.2f})" for x in item_data['history']]
                history_path = " > ".join(history_str_list)
                
                summary_msg = (f"<div style='margin-bottom:15px;'>"
                               f"<b>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"开盘 ¥{start_price:.2f} ➡️ 收盘 <b>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span><br>"
                               f"📊 今日最高: ¥{day_high:.2f} | 最低: ¥{day_low:.2f}<br>"
                               f"👑 {high_str}<br>"
                               f"🔥 24h热度: {volume} 笔成交 | 中位价: {median}<br>"
                               f"<img src='{chart_url}' alt='走势图' style='width:100%; max-width:300px; margin-top:5px;'><br>"
                               f"<div style='font-size:11px; color:#888; margin-top:4px; padding:4px; background:#f5f5f5; border-radius:4px;'>"
                               f"全天轨迹: {history_path}</div>"
                               f"</div>")
                daily_summary.append((net_change, summary_msg))
            
            # 复盘后重置，为第二天做准备（保留 historical_high 不被清除）
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]

        time.sleep(4)

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    if hourly_alerts:
        send_wxpusher(f"📈 CS2饰品异动通知 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<hr>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 CS2饰品今日大盘复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

if __name__ == "__main__":
    main()
