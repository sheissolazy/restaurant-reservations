# 订位提醒 Restaurant Reservations

难订餐厅放票日历 + 提前一天手机推送（自用）。独立静态站，不依赖任何后端。

## 它做什么
- 维护每家餐厅的「放票规则」（`pipeline/fetch_reservations.py` 里的 `RESTAURANTS`）。
- 每天算出下一个开放预订日，写到 `public/data/reservations.json`。
- 前端日历高亮**定时放票**日（如每月 1 号），列出**滚动放票**窗口（提前 N 天）。
- GitHub Actions 每天跑，对**明天放票**的标的发 ntfy 推送。

无假数据原则：放票**时间**未经官方核实的标 `verifiedTime:false`，前端显示「时间待确认」，
也不会触发自动推送——绝不编造时间提醒。

## 本地开发
```bash
npm install
npm run dev                       # 前端
python3 pipeline/fetch_reservations.py   # 重新生成 reservations.json（仅标准库）
```

## 开启手机推送（2 步）
1. 手机装 [ntfy](https://ntfy.sh) app，订阅一个只有你知道的 topic（如 `myc-resos-x7q2`）。
2. 仓库 Settings → Secrets → 新增 `NTFY_TOPIC` = 该 topic 名。

之后每天早上，对「明天放票」且时间已核实的标的（目前 Canlis / Archipelago / Ltd Edition）会推送到手机。

## 加城市 / 改规则
只动 `pipeline/fetch_reservations.py` 的 `RESTAURANTS` 表。当前为 Seattle 10 家。

## 待办
- 自动订位（Phase 2）：仅对 1–2 家必抢的做半自动脚本，触碰真实账号，按需再建。
- 未核实的放票规律（Pink Door / Kamonegi / Communion / Musang / Carrello / Taneda）需再确认。
