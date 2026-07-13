import requests
import json
import os
import datetime
import urllib.parse

# ================= 配置区域 =================
WXPUSHER_APP_TOKEN = "AT_yHKSDVeK6iT5WJO6UEgHybzBaA0dBpGa"
WXPUSHER_UID = "UID_xpTn3FaNA1yWqDvDMQJYurXEen72"
STEAM_ID = "76561199123057301"
DATA_FILE = "advanced_data.json"

MIN_ITEM_VALUE = 0.5       
MIN_INCREASE_PERCENT = 1.0 
# ============================================

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9"
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
        res = session.get(url, timeout=15)
        if res.status_code == 429:
            print("[警告] 获取库存被 Steam 限流 (429)")
            return {}
        try:
            data = res.json()
        except:
            print("[错误] 获取库存失败，返回非JSON数据")
            return {}
            
        for item in data.get('descriptions', []):
            if item.get('marketable'):
                hash_name = item['market_hash_name']
                items[hash_name] = item.get('name', hash_name)
        return items
    except Exception as e: 
        print(f"[错误] 获取库存异常: {e}")
        return {}

def fetch_all_market_data():
    """
    【降维打击】使用 Skinport 官方 API 一次性拉取全网所有饰品数据！
    彻底告别一个一个查价格，0 延迟，0 封禁风险。
    """
    url = "https://api.skinport.com/v1/items"
    params = {"app_id": 730, "currency": "CNY", "tradable": 0}
    
    print("[提示] 正在从 Skinport 获取全球大盘价格 (只需几秒)...")
    try:
        res = session.get(url, params=params, timeout=20)
        data = res.json()
        
        market_dict = {}
        for item in data:
            name = item.get("market_hash_name")
            if not name: continue
            
            # 优先取市场最低在售价，如果没有则取系统建议价
            price = item.get("min_price") or item.get("suggested_price") or -1
            
            market_dict[name] = {
                "price": float(price),
                "volume": item.get("quantity", 0),
                "median": item.get("mean_price", "未知"),
                "high_24h": item.get("max_price", "未知")
            }
            
        print(f"[成功] 全球大盘拉取完成，共载入 {len(market_dict)} 件饰品数据！")
        return market_dict
    except Exception as e:
        print(f"[错误] 大盘数据拉取失败: {e}")
        return {}
        
def generate_sparkline_url(prices, is_red):
    if not prices: return ""
    if len(prices) == 1: prices.append(prices[0])
    
    color = "rgb(255, 77, 79)" if is_red else "rgb(82, 196, 26)"
    bg_color = "rgba(255, 77, 79, 0.1)" if is_red else "rgba(82, 196, 26, 0.1)"
    
    prices_str = ",".join(map(str, prices))
    config_str = (
        f"{{type:'sparkline',data:{{datasets:[{{"
        f"data:[{prices_str}],fill:true,backgroundColor:'{bg_color}',"
        f"borderColor:'{color}',borderWidth:2,pointRadius:0"
        f"}}]}}}}"
    )
    encoded_config = urllib.parse.quote(config_str)
    return f"https://quickchart.io/chart?w=300&h=80&bkg=white&c={encoded_config}"

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    
    is_11_pm = (now_bj.hour >= 22)

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
        print("[提示] 库存为空或获取失败，结束运行。")
        return
        
    # ================= 极速引擎核心 =================
    global_market_data = fetch_all_market_data()
    if not global_market_data:
        print("[错误] 大盘数据为空，任务中止。")
        return
    # ================================================

    hourly_alerts = []
    daily_summary = []
    valid_items_checked = 0 

    for hash_name, cn_name in inventory_items.items():
        market_data = global_market_data.get(hash_name)
        
        if not market_data:
            continue
            
        price = market_data["price"]
        volume = market_data["volume"]
        median = market_data["median"]
        high_24h = market_data["high_24h"]
        
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and hash_name in db:
                db[hash_name]["start_price"] = db[hash_name].get("last_price", 0)
                db[hash_name]["history"] = [{"time": "昨日收盘", "price": db[hash_name]["start_price"]}]
            continue
            
        valid_items_checked += 1
        
        if hash_name not in db:
            db[hash_name] = {
                "start_price": price, 
                "last_price": price, 
                "history": [{"time": current_time_str, "price": price}],
                "historical_high": price 
            }
        else:
            old_history = db[hash_name].get("history", [])
            db[hash_name]["history"] = [h if isinstance(h, dict) else {"time": "历史", "price": float(h)} for h in old_history]
            if "historical_high" not in db[hash_name]:
                highest_past = max([x["price"] for x in db[hash_name]["history"]] + [db[hash_name].get("start_price", price)])
                db[hash_name]["historical_high"] = highest_past
                
        item_data = db[hash_name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        historical_high = item_data["historical_high"]
        
        # ========== 1. 常规异动监控 (白天触发) ==========
        if price > last_price:
            increase_percent = ((price - last_price) / last_price) * 100
            if increase_percent >= MIN_INCREASE_PERCENT:
                
                if price > historical_high:
                    high_tag = "🚀 <span style='color:red;'><b>强势突破历史新高！</b></span>"
                    item_data["historical_high"] = price 
                else:
                    high_tag = "📈 价格回升 (盘中异动)"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b style='font-size:16px;'>{cn_name}</b><br>"
                       f"当前状态：{high_tag}<br>"
                       f"现金底价：¥{last_price:.2f} ➡️ <b style='font-size:15px; color:#d9534f;'>¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"<div style='font-size:12px; color:#555; background:#f5f5f5; padding:6px; border-radius:4px; margin-top:6px;'>"
                       f"<b>大盘参考：</b><br>"
                       f"在售件数: {volume} 件 | 均价参考: ¥{median}<br>"
                       f"</div></div>")
                hourly_alerts.append(msg)
        
        # 记录全天波动轨迹
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 2. 晚间复盘逻辑 ==========
        if should_generate_daily:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            
            if abs(net_change) >= MIN_INCREASE_PERCENT or len(item_data['history']) > 1:
                trend_color = "#d9534f" if net_change > 0 else "#5cb85c"
                is_red_chart = (net_change >= 0)
                
                all_prices_today = [start_price] + [x['price'] for x in item_data['history']]
                if price not in all_prices_today: all_prices_today.append(price)
                
                day_high = max(all_prices_today)
                day_low = min(all_prices_today)
                
                chart_url = generate_sparkline_url(all_prices_today, is_red_chart)
                
                if day_high > historical_high:
                    high_str = f"<span style='color:#d9534f;'><b>🎊 突破历史新高 (原纪录 ¥{historical_high:.2f})！</b></span>"
                    item_data["historical_high"] = day_high
                else:
                    high_str = f"距历史高位 (¥{historical_high:.2f}) 差 ¥{(historical_high - day_high):.2f}"

                history_str_list = [f"{x['time']}(¥{x['price']:.2f})" for x in item_data['history']]
                history_path = " > ".join(history_str_list)
                
                summary_msg = (f"<div style='margin-bottom:20px;'>"
                               f"<b style='font-size:15px;'>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"今日收盘：<b style='font-size:16px;'>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span> "
                               f"<span style='font-size:12px; color:#888;'>(开盘 ¥{start_price:.2f})</span><br>"
                               f"📊 今日探底: ¥{day_low:.2f} | 冲高: ¥{day_high:.2f}<br>"
                               f"👑 {high_str}<br>"
                               f"<div style='font-size:12px; color:#31708f; background:#d9edf7; padding:6px; border-radius:5px; margin:6px 0;'>"
                               f"🛒 <b>全网真实交易底价 (Skinport API)</b><br>"
                               f"在售件数: {volume} 件 | 平均参考价: ¥{median}<br>"
                               f"最高挂单: ¥{high_24h}"
                               f"</div>"
                               f"<img src='{chart_url}' alt='走势图' style='width:100%; max-width:300px; margin-top:2px; border-radius:4px;'><br>"
                               f"<div style='font-size:11px; color:#888; margin-top:6px; padding:4px; background:#f9f9f9; border:1px solid #eee; border-radius:4px;'>"
                               f"<b>盘中轨迹:</b> {history_path}</div>"
                               f"</div>")
                daily_summary.append((net_change, summary_msg))
            
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    if hourly_alerts:
        send_wxpusher(f"📈 饰品异动雷达 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<hr style='border:1px dashed #ccc;'>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 饰品大盘深度复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

    # ================= 存活心跳 (测试用) =================
    if not hourly_alerts and not daily_summary and valid_items_checked > 0:
        send_wxpusher(f"✅ 监控打卡 ({current_time_str})", f"极速引擎运行正常！<br>瞬间获取并匹配了 {valid_items_checked} 件饰品的真实底价。<br>目前大盘平稳，未达到报警阈值。")

if __name__ == "__main__":
    main()