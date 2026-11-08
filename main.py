"""
Tencent 0700.HK Monitor
功能：
1. 2026-11-18 腾讯Q3财报日提醒，并尝试抓取最新季度利润表数据
2. 股价进入 550–600 HKD 区间时提醒，用于触发“剩余转换评估”
"""

import time
import json
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, date
import urllib.request

import yfinance as yf

# ================= 配置 =================
TICKER = "0700.HK"
EARNINGS_DATE = date(2026, 11, 18)          # 腾讯Q3财报日
PRICE_LOW = 550.0
PRICE_HIGH = 600.0
CHECK_INTERVAL_SECONDS = 300                 # 股价每 5 分钟检查一次
STATE_FILE = "tencent_monitor_state.json"

# 邮件通知（可选，不填则只打印到控制台）
SMTP_SERVER = ""          # e.g. smtp.qq.com
SMTP_PORT = 465
SMTP_USER = ""
SMTP_PASSWORD = ""
TO_EMAIL = ""             # 接收提醒的邮箱

# ========================================


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"earnings_alerted": False, "price_alerted": False}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_notification(subject, body):
    """控制台打印 + 可选邮件发送"""
    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {subject}")
    print(body)
    print("=" * 60)

    if not SMTP_SERVER or not TO_EMAIL:
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = TO_EMAIL

        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [TO_EMAIL], msg.as_string())
        server.quit()
        print("邮件已发送")
    except Exception as e:
        print(f"邮件发送失败: {e}")


def get_realtime_price():
    """新浪财经港股实时接口，字段[6]为当前价"""
    url = "http://hq.sinajs.cn/list=rt_hk00700"
    try:
        req = urllib.request.Request(
            url, headers={"Referer": "https://finance.sina.com.cn/"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk")
        # 返回格式: var hq_str_rt_hk00700="腾讯控股,...";
        raw = text.split('"')[1]
        fields = raw.split(",")
        price = float(fields[6])
        return price
    except Exception:
        return None


def fetch_earnings_data():
    """尝试用 yfinance 获取腾讯最新季度利润表核心字段"""
    try:
        t = yf.Ticker(TICKER)
        q = t.quarterly_income_stmt
        if q is None or q.empty:
            return "yfinance 暂未返回季度利润表数据。"

        latest_col = q.columns[0]
        lines = [f"最新报告期: {latest_col}"]
        for key in ["Total Revenue", "Net Income", "Operating Income", "Diluted EPS"]:
            if key in q.index:
                val = q.loc[key, latest_col]
                lines.append(f"{key}: {val:,.0f}" if isinstance(val, (int, float)) else f"{key}: {val}")
        return "\n".join(lines)
    except Exception as e:
        return f"财报数据抓取失败: {e}"


def check_price(state):
    price = get_realtime_price()
    if price is None:
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 腾讯当前价: {price:.1f} HKD", end="\r")

    in_range = PRICE_LOW <= price <= PRICE_HIGH

    if in_range and not state["price_alerted"]:
        send_notification(
            "🔔 腾讯进入 550–600 HKD 区间 — 触发剩余转换评估",
            f"当前价: {price:.1f} HKD\n"
            f"目标区间: {PRICE_LOW}–{PRICE_HIGH} HKD\n\n"
            f"此区间大致对应远期 Non-IFRS PE 15–16 倍附近。\n"
            f"建议按此前框架评估剩余仓位的转换节奏，\n"
            f"优先考虑纳指100（盈利增速更高、与AI主线更直接对齐）。"
        )
        state["price_alerted"] = True
        save_state(state)

    elif not in_range and state["price_alerted"]:
        # 离开区间后重置，允许下次重新触发
        state["price_alerted"] = False
        save_state(state)


def check_earnings(state):
    today = date.today()
    if today < EARNINGS_DATE:
        return

    if state["earnings_alerted"]:
        return

    data_text = fetch_earnings_data()
    send_notification(
        "📊 腾讯 2026 Q3 财报日提醒",
        f"今天是腾讯Q3财报披露日（2026-11-18）。\n\n"
        f"关键观察点：Non-IFRS 归母净利润同比降幅落在预测区间上沿还是下沿。\n"
        f"机构预测区间大致为 -3% 至 -9%。\n\n"
        f"—— 尝试抓取的财报数据 ——\n{data_text}\n\n"
        f"若利润降幅接近 -3%~-5% 且 AI 投入指引不再恶化，\n"
        f"腾讯的修复逻辑尚存，部分转换（20–30%）即可；\n"
        f"若接近或超过 -9%，转换紧迫性上升，可考虑提升至 50% 以上。"
    )
    state["earnings_alerted"] = True
    save_state(state)


def main():
    state = load_state()
    print("腾讯监控程序已启动。按 Ctrl+C 停止。")

    while True:
        try:
            check_earnings(state)
            check_price(state)
            time.sleep(CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\n程序已停止。")
            break
        except Exception as e:
            print(f"\n运行异常: {e}，60 秒后重试。")
            time.sleep(60)


if __name__ == "__main__":
    main()
