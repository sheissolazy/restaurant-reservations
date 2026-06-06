"""餐厅订位提醒：从「放票规则」算出每家的下一个开放预订日 → public/data/reservations.json。

为什么不是 24/7 爬虫：难订餐厅基本是「可预测的放票时间表」——
  - scheduled_drop：固定日子放票（如每月 1 号 12:00 PT 放下个月）
  - rolling：滚动提前 N 天（如提前 60 天，每天都在放 N 天后那一天）
所以「下次开放日」是可计算的，不用抢，只需算 + 提前一天推送。

无假数据原则：放票「时间点」没核实的，verifiedTime=False，前端显示「时间待确认」，
  推送任务也拒绝对未核实时间触发，绝不编造一个时间去提醒。

用法（仅标准库，无需 pip install）：
  python3 fetch_reservations.py                # 仅生成 reservations.json
  python3 fetch_reservations.py --notify       # 生成 + 对「明天放票」的标的发 T-1 天「准备一下」推送
  python3 fetch_reservations.py --notify-open  # 生成 + 对「此刻正在放票」的标的发「立刻订」直达推送
                                               #   两者都需环境变量 NTFY_TOPIC（可选 NTFY_SERVER，默认 ntfy.sh）
                                               #   --notify-open 由高频 cron（每 ~10 分钟）调用，命中放票时刻才推；
                                               #   用 push_state.json 去重，确保每次放票只推一次。
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "public", "data")
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
PUSH_STATE_PATH = os.path.join(PIPELINE_DIR, "push_state.json")
TODAY = dt.date.today()
PT = ZoneInfo("America/Los_Angeles")

# 「立刻订」推送的命中窗口：放票时刻起 OPEN_WINDOW_MIN 分钟内，高频 cron 一旦撞上就推一次。
# 给足余量是因为 GitHub Actions cron 常有几分钟漂移；用 push_state.json 去重避免重复推。
OPEN_WINDOW_MIN = 25


def write_json(rel_path, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, rel_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  ✓ wrote {os.path.relpath(path, ROOT)}")


# ---- 放票规则表（单一事实来源；新增/改一家只动这里）----
# model: "scheduled_drop" | "rolling" | "unknown"
#   scheduled_drop.drop = {dayOfMonth, time "HH:MM", monthsAhead}（按 PT 时区）
#     nextDropOverride = "YYYY-MM-DDTHH:MM"（PT）：节奏不固定时，人工写死下一次已公布的放票时刻
#   rolling.rolling = {daysAhead, time}（time 可为 None=未核实）
# prepaid: "full" | "deposit" | "none" | "unknown"
# confidence: "high" | "medium" | "low"
# verifiedTime: 放票「时间点」是否经官方核实（False → 前端标「时间待确认」，不触发定时推送）
RESTAURANTS = [
    {
        "id": "ltdedition", "name": "Ltd Edition Sushi", "cuisine": "日式 omakase", "city": "Seattle",
        "platform": "tock", "bookingUrl": "https://www.exploretock.com/ltdeditionsushi",
        "priceNote": "~$225（预付）", "prepaid": "full",
        "model": "scheduled_drop",
        # 放票节奏不固定，按官方公布日期；下一次已公布为 2026-06-15 18:00 PT（到期需核实更新）
        "nextDropOverride": "2026-06-15T18:00",
        "confidence": "medium", "verifiedTime": True,
        "notes": "分批不定期放票，按官方公布日期；下一次 2026-06-15 18:00 PT。单人请上 waitlist 注明「for one」。",
        "source": "https://www.exploretock.com/ltdeditionsushi",
    },
    {
        "id": "taneda", "name": "Taneda", "cuisine": "江户前寿司 omakase", "city": "Seattle",
        "platform": "tock", "bookingUrl": "https://www.exploretock.com/taneda",
        "priceNote": "$255 + 20% 服务费（预付）", "prepaid": "full",
        "model": "scheduled_drop",
        # 估计：每月「倒数第二个周六」11:00 PT 放下月（IG 公布、历史有漂移）→ verifiedTime=False，上日历但不自动推送
        "drop": {"weekday": 5, "weekdayFromEnd": 2, "time": "11:00", "monthsAhead": 1},
        "confidence": "medium", "verifiedTime": False,
        "notes": "估计每月倒数第二个周六 11:00 PT 放下月、约 30 分钟售罄；具体日子以 IG 公布为准（历史有漂移，故标「时间待确认」、不自动推送）。Tock 预付全款、48 小时取消不退。",
        "source": "https://www.theinfatuation.com/seattle/guides/toughest-restaurant-reservations-seattle",
    },
]


def _next_monthly_drop(now_pt, day_of_month, hh, mm):
    """从 now_pt 起，下一个「几号 HH:MM」的 PT datetime（>= now）。"""
    y, m = now_pt.year, now_pt.month
    for _ in range(3):
        try:
            cand = dt.datetime(y, m, day_of_month, hh, mm, tzinfo=PT)
        except ValueError:
            cand = None
        if cand and cand >= now_pt:
            return cand
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return None


def _next_weekday_from_end_drop(now_pt, weekday, from_end, hh, mm):
    """下一个「当月倒数第 from_end 个 <weekday>」HH:MM 的 PT datetime（>= now）。
    weekday: Mon=0 … Sat=5 … Sun=6。from_end=2 → 倒数第二个。"""
    y, m = now_pt.year, now_pt.month
    for _ in range(3):
        last_day = (dt.date(y, m + 1, 1) - dt.timedelta(days=1)).day if m < 12 else 31
        matches = [d for d in range(1, last_day + 1) if dt.date(y, m, d).weekday() == weekday]
        if len(matches) >= from_end:
            cand = dt.datetime(y, m, matches[-from_end], hh, mm, tzinfo=PT)
            if cand >= now_pt:
                return cand
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return None


def _scheduled_drop_at(r, ref):
    """从 ref 时刻起，这家 scheduled_drop 餐厅的下一个放票 PT datetime（>= ref）。
    优先用人工写死的 nextDropOverride；否则按 drop 规则（每月几号 / 当月倒数第几个周几）。
    notify_open 会传 ref = now - 窗口，好让「刚开始的放票」也能被认出来。"""
    ov = r.get("nextDropOverride")
    if ov:
        cand = dt.datetime.fromisoformat(ov).replace(tzinfo=PT)
        if cand >= ref:
            return cand
        return None
    if "drop" in r:
        d = r["drop"]
        hh, mm = (int(x) for x in d["time"].split(":"))
        if "weekdayFromEnd" in d:
            return _next_weekday_from_end_drop(ref, d["weekday"], d["weekdayFromEnd"], hh, mm)
        return _next_monthly_drop(ref, d["dayOfMonth"], hh, mm)
    return None


def compute(r, now_pt):
    """把放票规则算成可渲染的下一个开放日字段（不改输入）。"""
    out = {
        "id": r["id"], "name": r["name"], "cuisine": r["cuisine"], "city": r["city"],
        "platform": r["platform"], "bookingUrl": r["bookingUrl"], "priceNote": r["priceNote"],
        "prepaid": r["prepaid"], "model": r["model"], "confidence": r["confidence"],
        "verifiedTime": r["verifiedTime"], "notes": r["notes"], "source": r["source"],
        "nextReleaseDate": None, "nextReleaseAt": None, "releaseLabel": None,
        "opensInDays": None, "rollingDaysAhead": None, "bookableThrough": None,
    }

    if r["model"] == "scheduled_drop":
        nxt = _scheduled_drop_at(r, now_pt)
        if nxt:
            out["nextReleaseDate"] = nxt.date().isoformat()
            out["nextReleaseAt"] = nxt.isoformat()
            out["opensInDays"] = (nxt.date() - now_pt.date()).days
            ma = r.get("drop", {}).get("monthsAhead")
            tail = "放下月" if ma == 1 else (f"放提前 {ma} 个月那档" if ma else "放新一批")
            est = "" if r["verifiedTime"] else "（估计）"
            out["releaseLabel"] = f"{nxt.month}/{nxt.day} {nxt.strftime('%H:%M')} PT{est} · {tail}"

    elif r["model"] == "rolling":
        n = r["rolling"]["daysAhead"]
        out["rollingDaysAhead"] = n
        if n:
            out["bookableThrough"] = (now_pt.date() + dt.timedelta(days=n)).isoformat()
            out["releaseLabel"] = f"滚动提前 {n} 天 · 今天可订至 {out['bookableThrough']}"
        else:
            out["releaseLabel"] = "滚动放票 · 窗口天数未核实"

    return out


def load_favorites():
    """读 favorites.json 的收藏 id 列表。文件不存在 → None（回退为「对所有已核实放票推送」）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favorites.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return list(json.load(f).get("favorites", []))
    except Exception as e:  # noqa
        print(f"  [notify] favorites.json 解析失败，回退为全部已核实：{e}", file=sys.stderr)
        return None


def notify(items):
    """只对「明天放票 + 时间已核实 + 在收藏名单内」的标的发 ntfy 推送。"""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("  [notify] 未设 NTFY_TOPIC，跳过推送")
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    tomorrow = (TODAY + dt.timedelta(days=1)).isoformat()
    favorites = load_favorites()
    due = [it for it in items if it["verifiedTime"] and it["nextReleaseDate"] == tomorrow]
    if favorites is not None:
        due = [it for it in due if it["id"] in favorites]
        print(f"  [notify] 收藏名单：{favorites}")
    if not due:
        print("  [notify] 明天无（收藏内的）已核实放票，跳过")
        return
    for it in due:
        title = f"明天放票：{it['name']}"
        body = f"{it['releaseLabel']}\n{it['cuisine']} · {it['priceNote']}\n要订就准点开抢 → {it['bookingUrl']}"
        try:
            req = urllib.request.Request(
                f"{server}/{topic}", data=body.encode("utf-8"),
                headers={
                    "Title": title.encode("utf-8").decode("latin-1", "ignore"),
                    "Click": it["bookingUrl"],
                    "Priority": "high",
                    "Tags": "fork_and_knife",
                },
            )
            urllib.request.urlopen(req, timeout=15).read()
            print(f"  [notify] ✓ 已推送 {it['name']}")
        except Exception as e:  # noqa
            print(f"  [notify] ✗ {it['name']} 推送失败：{e}", file=sys.stderr)


def load_push_state():
    """读 push_state.json 的「已推过的放票时刻」集合，用于去重。文件不存在 → 空。"""
    if not os.path.exists(PUSH_STATE_PATH):
        return {"opened": []}
    try:
        with open(PUSH_STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
            st.setdefault("opened", [])
            return st
    except Exception as e:  # noqa
        print(f"  [open] push_state.json 解析失败，当作空：{e}", file=sys.stderr)
        return {"opened": []}


def save_push_state(state):
    # 只保留最近 50 条，避免无限增长
    state["opened"] = state.get("opened", [])[-50:]
    with open(PUSH_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"  [open] ✓ wrote {os.path.relpath(PUSH_STATE_PATH, ROOT)}")


def _ntfy_post(title, body, click, tags, priority):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("  [push] 未设 NTFY_TOPIC，跳过推送")
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


def notify_open(now_pt):
    """「立刻订」：对此刻正处于放票窗口（放票时刻起 OPEN_WINDOW_MIN 分钟内）、
    时间已核实、且在收藏名单内的标的，发一条直达 Tock 的高优先级推送。
    用 push_state.json 按「id@放票时刻」去重，确保每次放票只推一次。
    关键：用 ref = now - 窗口 去找放票时刻，这样「刚刚开始的放票」也能被认出来
    （compute() 只给未来的放票，不能用于此处）。"""
    if not os.environ.get("NTFY_TOPIC"):
        print("  [open] 未设 NTFY_TOPIC，跳过推送")
        return
    favorites = load_favorites()
    state = load_push_state()
    opened = set(state["opened"])
    window = dt.timedelta(minutes=OPEN_WINDOW_MIN)
    ref = now_pt - window

    fired_any = False
    for r in RESTAURANTS:
        if r["model"] != "scheduled_drop" or not r.get("verifiedTime"):
            continue
        if favorites is not None and r["id"] not in favorites:
            continue
        drop_at = _scheduled_drop_at(r, ref)
        if not drop_at or not (drop_at <= now_pt < drop_at + window):
            continue
        key = f"{r['id']}@{drop_at.isoformat()}"
        if key in opened:
            print(f"  [open] {r['name']} 本次放票已推过，跳过")
            continue
        info = compute(r, drop_at)  # 拿 releaseLabel 等展示字段
        title = f"现在放票：{r['name']} — 立刻订"
        body = (
            f"{info['releaseLabel']}\n{r['cuisine']} · {r['priceNote']}\n"
            f"手机已登录 Tock，约 2 步确认+付款 → 点开直达"
        )
        try:
            if _ntfy_post(title, body, r["bookingUrl"], "rotating_light", "urgent"):
                opened.add(key)
                fired_any = True
                print(f"  [open] ✓ 已推送「立刻订」{r['name']}")
        except Exception as e:  # noqa
            print(f"  [open] ✗ {r['name']} 推送失败：{e}", file=sys.stderr)

    if fired_any:
        state["opened"] = sorted(opened)
        save_push_state(state)
    else:
        print("  [open] 此刻无（收藏内的）已核实放票在窗口内，跳过")


def main():
    now_pt = dt.datetime.now(PT)
    items = [compute(r, now_pt) for r in RESTAURANTS]

    def sort_key(it):
        if it["nextReleaseDate"]:
            return (0, it["nextReleaseDate"])
        if it["model"] == "rolling":
            return (1, it["name"])
        return (2, it["name"])
    items.sort(key=sort_key)

    write_json("reservations.json", {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "today": TODAY.isoformat(),
        "city": "Seattle",
        "items": items,
    })

    if "--notify" in sys.argv:
        notify(items)
    if "--notify-open" in sys.argv:
        notify_open(now_pt)


if __name__ == "__main__":
    main()
