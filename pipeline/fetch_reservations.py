"""餐厅订位提醒：从「放票规则」算出每家的下一个开放预订日 → public/data/reservations.json。

为什么不是 24/7 爬虫：难订餐厅基本是「可预测的放票时间表」——
  - scheduled_drop：固定日子放票（如每月 1 号 12:00 PT 放下个月）
  - rolling：滚动提前 N 天（如提前 60 天，每天都在放 N 天后那一天）
所以「下次开放日」是可计算的，不用抢，只需算 + 提前一天推送。

无假数据原则：放票「时间点」没核实的，verifiedTime=False，前端显示「时间待确认」，
  推送任务也拒绝对未核实时间触发，绝不编造一个时间去提醒。

用法（仅标准库，无需 pip install）：
  python3 fetch_reservations.py            # 仅生成 reservations.json
  python3 fetch_reservations.py --notify   # 生成 + 对「明天放票」的标的发 ntfy 推送
                                           #   需环境变量 NTFY_TOPIC（可选 NTFY_SERVER，默认 ntfy.sh）
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "public", "data")
TODAY = dt.date.today()
PT = ZoneInfo("America/Los_Angeles")


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
        "id": "canlis", "name": "Canlis", "cuisine": "PNW 精致餐饮", "city": "Seattle",
        "platform": "tock", "bookingUrl": "https://www.exploretock.com/canlis",
        "priceNote": "tasting ~$165", "prepaid": "deposit",
        "model": "scheduled_drop",
        "drop": {"dayOfMonth": 1, "time": "12:00", "monthsAhead": 1},
        "confidence": "high", "verifiedTime": True,
        "notes": "每月 1 号 12:00 PT 放下个月；可退订至到店前 48 小时。Bar 可 walk-in 喝一杯。",
        "source": "https://www.exploretock.com/canlis",
    },
    {
        "id": "archipelago", "name": "Archipelago", "cuisine": "进步派菲律宾裔美式 tasting", "city": "Seattle",
        "platform": "tock", "bookingUrl": "https://www.exploretock.com/archipelagoseattle",
        "priceNote": "$275/人（预付，不退可转）", "prepaid": "full",
        "model": "scheduled_drop",
        "drop": {"dayOfMonth": 1, "time": "14:00", "monthsAhead": 2},
        "confidence": "high", "verifiedTime": True,
        "notes": "每月 1 号 14:00 PT 一次放出两个月（提前 2 个月那一档）。Waitlist=已满，靠转票放出。",
        "source": "https://www.exploretock.com/archipelagoseattle",
    },
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
        "id": "spinasse", "name": "Spinasse", "cuisine": "北意 / 皮埃蒙特", "city": "Seattle",
        "platform": "opentable", "bookingUrl": "https://www.opentable.com/r/spinasse-seattle",
        "priceNote": "à la carte ~$70–$110", "prepaid": "none",
        "model": "rolling",
        "rolling": {"daysAhead": 60, "time": None},
        "confidence": "high", "verifiedTime": False,
        "notes": "滚动提前 60 天放票（具体放票时刻未核实）。需信用卡担保，48 小时内取消/未到 $30/人。5–8 人邮件或电话。",
        "source": "https://www.opentable.com/r/spinasse-seattle",
    },
    {
        "id": "pinkdoor", "name": "The Pink Door", "cuisine": "意式（含 cabaret）", "city": "Seattle",
        "platform": "opentable", "bookingUrl": "https://www.opentable.com/r/the-pink-door-seattle",
        "priceNote": "à la carte ~$60–$90", "prepaid": "none",
        "model": "rolling",
        "rolling": {"daysAhead": 90, "time": None},
        "confidence": "medium", "verifiedTime": False,
        "notes": "滚动提前 90 天（来自搜索摘要，放票时刻未核实）。留有 16 个吧台位 + 部分桌位给 walk-in。",
        "source": "https://www.opentable.com/r/the-pink-door-seattle",
    },
    {
        "id": "kamonegi", "name": "Kamonegi", "cuisine": "手打荞麦面 / 日式 kaiseki", "city": "Seattle",
        "platform": "tock", "bookingUrl": "https://www.exploretock.com/kamonegiseattle",
        "priceNote": "kaiseki ~$100+", "prepaid": "unknown",
        "model": "rolling",
        "rolling": {"daysAhead": 30, "time": None},
        "confidence": "low", "verifiedTime": False,
        "notes": "约滚动提前 30 天（天数与时刻均未核实）。吧台/柜台接受 ≤5 人 walk-in。",
        "source": "https://www.exploretock.com/kamonegiseattle",
    },
    {
        "id": "musang", "name": "Musang", "cuisine": "菲律宾", "city": "Seattle",
        "platform": "opentable", "bookingUrl": "https://www.opentable.com/r/musang-seattle",
        "priceNote": "à la carte ~$50–$80", "prepaid": "deposit",
        "model": "rolling",
        "rolling": {"daysAhead": None, "time": None},   # 已核实为滚动放票；窗口天数 N 官方未公布
        "confidence": "medium", "verifiedTime": False,
        "notes": "滚动放票（窗口天数未核实）：周中常有当天位，周末黄金时段约提前 1–2 周。含订位费桌（$375–$450 抵餐费）、$75/人低消、72 小时取消。吧台 + 部分桌位可 walk-in（1–4 人）。",
        "source": "https://www.theinfatuation.com/seattle/guides/previously-impossible-reservations-you-can-get-now-seattle",
    },
    {
        "id": "carrello", "name": "Carrello", "cuisine": "意式", "city": "Seattle",
        "platform": "sevenrooms", "bookingUrl": "https://www.carrellorestaurant.com/",
        "priceNote": "à la carte ~$80–$120", "prepaid": "none",
        "model": "rolling",
        "rolling": {"daysAhead": 300, "time": None},   # 实测 SevenRooms 可订约 300 天后，无放票闸门
        "confidence": "high", "verifiedTime": False,
        "notes": "SevenRooms 直订，无放票闸门——实测可订约 300 天后的位子，订满为止。周三至周日营业（周一二休）。7 人以上电话 206-257-5622。48 小时取消 $25/人。",
        "source": "https://www.carrellorestaurant.com/faq",
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
        nxt = None
        ov = r.get("nextDropOverride")
        if ov:
            cand = dt.datetime.fromisoformat(ov).replace(tzinfo=PT)
            if cand >= now_pt:
                nxt = cand
        if nxt is None and "drop" in r:
            d = r["drop"]
            hh, mm = (int(x) for x in d["time"].split(":"))
            if "weekdayFromEnd" in d:
                nxt = _next_weekday_from_end_drop(now_pt, d["weekday"], d["weekdayFromEnd"], hh, mm)
            else:
                nxt = _next_monthly_drop(now_pt, d["dayOfMonth"], hh, mm)
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


if __name__ == "__main__":
    main()
