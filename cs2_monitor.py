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

# CSQAQ 国内真实数据 API Token
CSQAQ_API_TOKEN = "JXJTD1B787E8L01767A8Z738" 

MIN_ITEM_VALUE = 0.5       
MIN_INCREASE_PERCENT = 1.0 

# 严格遵守官方 1次/秒 的限制，1.5 秒极速又稳妥
REQUEST_DELAY = 1.5
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
    except: pass

def bind_dynamic_ip():
    """【黑科技】每次启动时，调用官方API，把 GitHub 分配的随机动态 IP 自动加入白名单！"""
    if not CSQAQ_API_TOKEN: return
    url = "https://api.csqaq.com/api/v1/sys/bind_local_ip"
    headers = {"ApiToken": CSQAQ_API_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.post(url, headers=headers, json={}, timeout=10)
        data = res.json()
        if data.get("code") == 200:
            print("[系统] 成功将当前 GitHub 节点 IP 自动绑定至 CSQAQ 白名单！")
        else:
            print(f"[系统提示] IP绑定状态: {data.get('msg')}")
    except Exception as e:
        print(f"[错误] 自动绑定IP发生异常: {e}")

def get_inventory():
    """获取库存 (仅向 Steam 发送 1 次请求)"""
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
            return {}
            
        for item in data.get('descriptions', []):
            if item.get('marketable'):
                hash_name = item['market_hash_name']
                items[hash_name] = item.get('name', hash_name)
        return items
    except: return {}

def get_csqaq_good_id(hash_name):
    """【API 第一步】通过名字搜索 CSQAQ 站内的专属 good_id"""
    if not CSQAQ_API_TOKEN: return None
    url = "https://api.csqaq.com/api/v1/info/get_good_id"
    headers = {"ApiToken": CSQAQ_API_TOKEN, "Content-Type": "application/json"}
    payload = {"page_index": 1, "page_size": 20, "search": hash_name}
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 429: return None
        
        res_json = res.json()
        if res_json.get("code") != 200:
            print(f"[ID拦截] {hash_name} 获取失败: {res_json.get('msg')}")
            return None
            
        data_dict = res_json.get("data", {}).get("data", {})
        for _, item in data_dict.items():
            if item.get("market_hash_name") == hash_name:
                return item.get("id")
    except Exception as e:
        pass
    return None

def get_csqaq_details(good_id):
    """【API 第二步】通过 good_id 直接获取全部精细数据 (包含 Steam 价格)"""
    url = f"https://api.csqaq.com/api/v1/info/good?id={good_id}"
    headers = {"ApiToken": CSQAQ_API_TOKEN}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 429: return None
        
        res_json = res.json()
        if res_json.get("code") != 200:
            print(f"[详情拦截] ID:{good_id} 获取失败: {res_json.get('msg')}")
            return None
            
        return res_json.get("data", {}).get("goods_info", {})
    except Exception as e:
        print(f"[错误] 获取 ID:{good_id} 详情异常: {e}")
    return None

def generate_sparkline_url(prices, is_red):
    if not prices: return ""
    if len(prices) == 1: prices.append(prices[0])
    color = "rgb(255, 77, 79)" if is_red else "rgb(82, 196, 26)"
    bg_color = "rgba(255, 77, 79, 0.1)" if is_red else "rgba(82, 196, 26, 0.1)"
    prices_str = ",".join(map(str, prices))
    config_str = (f"{{type:'sparkline',data:{{datasets:[{{"
                  f"data:[{prices_str}],fill:true,backgroundColor:'{bg_color}',"
                  f"borderColor:'{color}',borderWidth:2,pointRadius:0"
                  f"}}]}}}}")
    return f"https://quickchart.io/chart?w=300&h=80&bkg=white&c={urllib.parse.quote(config_str)}"

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
    if not inventory_items: 
        print("[提示] 库存为空或获取失败，结束运行。")
        return

    hourly_alerts = []
    daily_summary = []
    valid_items_checked = 0 

    print("[启动] 核心监控系统启动...")
    # 🔥 核心突破：自动把 GitHub 当前 IP 绑定到你的 CSQAQ 账户
    bind_dynamic_ip()
    print("[提示] 正在基于 CSQAQ 官方文档接口拉取 Steam 价格...")

    for hash_name, cn_name in inventory_items.items():
        
        if hash_name not in db:
            db[hash_name] = {"history": []}
            
        item_data = db[hash_name]
        
        # ========== 智能记忆 ID 提速 ==========
        good_id = item_data.get("csqaq_id")
        if not good_id:
            good_id = get_csqaq_good_id(hash_name) 
            time.sleep(REQUEST_DELAY) 
            if good_id:
                item_data["csqaq_id"] = good_id
            else:
                continue 
                
        # ========== 核心：拉取饰品全盘详情 ==========
        details = get_csqaq_details(good_id)
        time.sleep(REQUEST_DELAY) 
        
        if not details:
            continue
            
        # 1. 绝对核心：提取 Steam 官方余额价格
        steam_sell = details.get("steam_sell_price") or details.get("steam_buy_price")
        if not steam_sell: 
            continue
            
        price = float(steam_sell)
        
        # 2. 极简辅核：只筛出全网(BUFF/悠悠/C5/ECO/IGXE)最高底价和求购价
        sell_prices = []
        buy_prices = []
        platforms = ["buff", "yyyp", "c5", "eco", "igxe"]
        
        for p in platforms:
            sp = details.get(f"{p}_sell_price")
            bp = details.get(f"{p}_buy_price")
            if sp and float(sp) > 0: sell_prices.append(float(sp))
            if bp and float(bp) > 0: buy_prices.append(float(bp))
                
        max_sell = f"¥{max(sell_prices):.2f}" if sell_prices else "未知"
        max_buy = f"¥{max(buy_prices):.2f}" if buy_prices else "未知"
        
        # 过滤低价值废品
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and "start_price" in item_data:
                item_data["start_price"] = item_data.get("last_price", 0)
                item_data["history"] = [{"time": "昨日收盘", "price": item_data["start_price"]}]
            continue
            
        valid_items_checked += 1

        # 新增饰品属性初始化
        if "start_price" not in item_data:
            item_data["start_price"] = price
            item_data["last_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]
            item_data["historical_high"] = price

        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        historical_high = item_data.get("historical_high", price)
        
        # ========== 常规异动监控 (绝对基于 Steam) ==========
        if price > last_price and last_price > 0:
            increase_percent = ((price - last_price) / last_price) * 100
            if increase_percent >= MIN_INCREASE_PERCENT:
                
                if price > historical_high:
                    high_tag = "🚀 <span style='color:red;'><b>突破 Steam 历史新高！</b></span>"
                    item_data["historical_high"] = price 
                else:
                    high_tag = "📈 Steam 价格回升"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b style='font-size:16px;'>{cn_name}</b><br>"
                       f"当前状态：{high_tag}<br>"
                       f"Steam余额价：¥{last_price:.2f} ➡️ <b style='font-size:15px; color:#d9534f;'>¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"<div style='font-size:11px; color:#666; background:#f9f9f9; padding:4px 6px; border-radius:4px; margin-top:6px;'>"
                       f"🛒 <b>国内现金参考:</b> 全网最高底价 {max_sell} | 最高求购 {max_buy}"
                       f"</div></div>")
                hourly_alerts.append(msg)
        
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 晚间复盘逻辑 (高低点折线图，以 Steam 为准) ==========
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
                               f"Steam 今日收盘：<b style='font-size:16px;'>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span><br>"
                               f"📊 Steam 探底: ¥{day_low:.2f} | 冲高: ¥{day_high:.2f}<br>"
                               f"👑 {high_str}<br>"
                               f"<div style='font-size:11px; color:#31708f; background:#d9edf7; padding:4px 6px; border-radius:4px; margin:6px 0;'>"
                               f"🛒 <b>国内辅助参考:</b> 全网最高底价 {max_sell} | 最高求购 {max_buy}"
                               f"</div>"
                               f"<img src='{chart_url}' alt='走势图' style='width:100%; max-width:300px; margin-top:2px; border-radius:4px;'><br>"
                               f"<div style='font-size:11px; color:#888; margin-top:6px; padding:4px; background:#f9f9f9; border:1px solid #eee; border-radius:4px;'>"
                               f"<b>Steam 盘中轨迹:</b> {history_path}</div>"
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
        send_wxpusher(f"📊 Steam 大盘深度复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

    if not hourly_alerts and not daily_summary and valid_items_checked > 0:
        send_wxpusher(f"✅ 监控打卡 ({current_time_str})", f"官方接口引擎运行正常！<br>已完成 {valid_items_checked} 件饰品的 Steam 价格排查。<br>目前大盘平稳，未达到报警阈值。")

if __name__ == "__main__":
    main()