"""盯 Instagram（默认 @tanedaseattle）的放票公告帖 → 有新帖就 ntfy 推送（自用，独立站）。

为什么用「你自己的登录 cookie」而不是官方 API：
  Instagram 官方 Graph API 只能读你自己/你管理的账号，读不到别家（@tanedaseattle）的公开帖。
  所以走和股票站 X 抓取同一条路：用你浏览器里的 IG 登录 cookie 调网页版私有 API。
  —— 零成本、脆弱、有账号风险（IG 可能要求验证/限流），与 X 同样的取舍。

无假数据原则：
  只做「检测到新帖 → 把原文 caption 原样推给你看」，绝不替你把 caption 解析成放票日期去自动提醒。
  日期由你看帖确认后，再回填到 fetch_reservations.py 的 Taneda（届时才标 verifiedTime=True，
  那条「立刻订」准点推送才会对 Taneda 生效）。

用法（仅标准库，无需 pip install）：
  IG_SESSIONID=... python3 watch_instagram.py            # 抓最新帖，更新 ig_state.json
  IG_SESSIONID=... python3 watch_instagram.py --notify   # 有新帖则 ntfy 推送

环境变量：
  IG_SESSIONID  （必需）你 IG 登录 cookie 里的 sessionid；没设则干净跳过（不报错、不发邮件）
  IG_CSRFTOKEN  （可选）cookie 里的 csrftoken，个别情况需要
  IG_USERNAMES  （可选）逗号分隔的要盯的账号，默认 "tanedaseattle"
  NTFY_TOPIC    （推送用）同 fetch_reservations；可选 NTFY_SERVER（默认 ntfy.sh）
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(PIPELINE_DIR, "ig_state.json")

# Instagram 网页版前端用的公共 app id（非私密，浏览器同样发送）；缺了它私有 API 会 403。
IG_APP_ID = "936619743392459"

DEFAULT_USERNAMES = ["tanedaseattle"]

# caption 命中这些词 → 这条很可能是放票/预订公告，推送标记为高优先级（仅提示，不解析日期）。
# 故意宽松：宁可多响一次，也别漏掉换了措辞的公告。
RES_KEYWORDS = [
    "reservation", "reservations", "reserve", "booking", "book now", "bookings",
    "seats", "seating", "available", "availability", "release", "released",
    "drop", "open", "opens", "opening", "tock", "waitlist", "next month",
    "july", "august", "september", "october", "november", "december", "january",
    "予約", "予約開始", "受付", "空席",
]


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"seen_ids": [], "auth_alerted": False}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
            st.setdefault("seen_ids", [])
            st.setdefault("auth_alerted", False)
            return st
    except Exception as e:  # noqa
        print(f"  [ig] ig_state.json 解析失败，当作空：{e}", file=sys.stderr)
        return {"seen_ids": [], "auth_alerted": False}


def save_state(state):
    state["seen_ids"] = state.get("seen_ids", [])[-200:]  # 只留最近 200 个 id，防无限增长
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"  [ig] ✓ wrote {os.path.relpath(STATE_PATH, PIPELINE_DIR)}")


def _ig_headers():
    sid = os.environ["IG_SESSIONID"]
    csrf = os.environ.get("IG_CSRFTOKEN", "")
    cookie = f"sessionid={sid}"
    if csrf:
        cookie += f"; csrftoken={csrf}"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "x-ig-app-id": IG_APP_ID,
        "Cookie": cookie,
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
    }
    if csrf:
        headers["x-csrftoken"] = csrf
    return headers


def _is_auth_error(exc):
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403):
        return True
    msg = str(exc).lower()
    return "login_required" in msg or "checkpoint" in msg or "csrf" in msg


def fetch_latest_posts(username, count=6):
    """用登录 cookie 调 web_profile_info 私有接口，取某账号最近若干条原创帖。"""
    url = ("https://www.instagram.com/api/v1/users/web_profile_info/"
           f"?username={urllib.parse.quote(username)}")
    req = urllib.request.Request(url, headers=_ig_headers())
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    user = (data.get("data") or {}).get("user") or {}
    edges = (user.get("edge_owner_to_timeline_media") or {}).get("edges") or []
    posts = []
    for e in edges[:count]:
        n = e.get("node") or {}
        caps = (n.get("edge_media_to_caption") or {}).get("edges") or []
        caption = caps[0]["node"]["text"] if caps else ""
        posts.append({
            "id": str(n.get("id") or ""),
            "shortcode": n.get("shortcode") or "",
            "caption": caption,
            "taken_at": n.get("taken_at_timestamp"),
        })
    return [p for p in posts if p["id"]]


def _looks_like_reservation(caption):
    low = caption.lower()
    return any(k in low for k in RES_KEYWORDS)


def _ntfy(title, body, click, tags, priority):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("  [ig] 未设 NTFY_TOPIC，跳过推送（仅更新状态）")
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(
        f"{server}/{topic}", data=body.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8").decode("latin-1", "ignore"),
            "Click": click,
            "Priority": priority,
            "Tags": tags,
        },
    )
    urllib.request.urlopen(req, timeout=15).read()
    return True


def _alert_auth_expired(state, notify):
    """cookie 失效时只提醒一次（去重），避免每小时刷屏；干净退出不让 workflow 失败。"""
    if notify and not state.get("auth_alerted"):
        try:
            if _ntfy("IG 监控：cookie 失效", "IG_SESSIONID 已过期，请更新仓库 secret 后恢复盯票。",
                     "https://www.instagram.com/", "warning", "default"):
                state["auth_alerted"] = True
                save_state(state)
        except Exception as e:  # noqa
            print(f"  [ig] 失效提醒发送失败：{e}", file=sys.stderr)
    print("  [ig] IG cookie 失效（login_required/checkpoint）→ 暂停盯票，请更新 IG_SESSIONID")


def run(notify):
    if not os.environ.get("IG_SESSIONID"):
        print("  [ig] 未设 IG_SESSIONID，跳过（按你 IG 登录 cookie 里的 sessionid 设仓库 secret）")
        return
    usernames = [u.strip() for u in os.environ.get("IG_USERNAMES", "").split(",") if u.strip()]
    if not usernames:
        usernames = DEFAULT_USERNAMES

    state = load_state()
    seen = set(state["seen_ids"])
    first_run = len(seen) == 0  # 首次运行：登记现有帖为已读，不要把历史帖全推一遍
    new_seen = []
    fired = 0

    for username in usernames:
        try:
            posts = fetch_latest_posts(username)
        except Exception as e:  # noqa
            if _is_auth_error(e):
                _alert_auth_expired(state, notify)
                return
            print(f"  [ig] 抓 @{username} 失败：{e} → 跳过本次", file=sys.stderr)
            continue
        state["auth_alerted"] = False  # 抓成功 → 清除失效标记
        for p in posts:
            if p["id"] in seen:
                continue
            new_seen.append(p["id"])
            seen.add(p["id"])
            if first_run:
                continue  # 首跑只登记，不推
            url = (f"https://www.instagram.com/p/{p['shortcode']}/"
                   if p["shortcode"] else "https://www.instagram.com/" + username + "/")
            cap = re.sub(r"\s+", " ", p["caption"]).strip()
            resv = _looks_like_reservation(cap)
            title = ("🍣 Taneda 可能在放票公告！" if resv else "Taneda 新帖")
            if username not in ("tanedaseattle",):
                title = (f"🔔 @{username} 可能在放票公告！" if resv else f"@{username} 新帖")
            body = (cap[:300] or "（无文字）") + "\n\n点开看原帖 → 自己确认放票日期"
            if notify:
                try:
                    if _ntfy(title, body, url, "fork_and_knife",
                             "urgent" if resv else "default"):
                        fired += 1
                        print(f"  [ig] ✓ 推送 @{username} {p['shortcode']}（resv={resv}）")
                except Exception as e:  # noqa
                    print(f"  [ig] ✗ 推送失败 {p['shortcode']}：{e}", file=sys.stderr)
            else:
                print(f"  [ig] 新帖 @{username} {p['shortcode']}（resv={resv}）")

    if new_seen:
        state["seen_ids"] = list(state["seen_ids"]) + new_seen
        save_state(state)
        if first_run:
            print(f"  [ig] 首次运行：登记 {len(new_seen)} 条现有帖为已读，不推送")
    else:
        print("  [ig] 无新帖")
    if not first_run:
        print(f"  [ig] 本次推送 {fired} 条")


if __name__ == "__main__":
    run("--notify" in sys.argv)
