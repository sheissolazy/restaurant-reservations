import { useJson } from './useJson'
import type { ReservationsData, ReservationItem } from './types'

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

const EMPTY: ReservationsData = { generatedAt: '', today: '', city: 'Seattle', items: [] }
const TODAY = new Date().toISOString().slice(0, 10)
const daysTo = (d: string) => Math.round((Date.parse(d) - Date.parse(TODAY)) / 86400000)

const PLATFORM_LABEL: Record<string, string> = {
  tock: 'Tock', opentable: 'OpenTable', sevenrooms: 'SevenRooms', resy: 'Resy', phone: '电话',
}
const PREPAID_LABEL: Record<string, string> = {
  full: '预付全款', deposit: '需押金', none: '免预付', unknown: '预付未知',
}

export default function App() {
  const { data, status } = useJson<ReservationsData>('reservations.json', EMPTY)
  const items = data.items

  const drops = items.filter((i) => i.model === 'scheduled_drop' && i.nextReleaseDate)
  const rolling = items.filter((i) => i.model === 'rolling')
  const unknown = items.filter((i) => i.model === 'unknown')

  const byDate = new Map<string, ReservationItem[]>()
  for (const d of drops) {
    const k = d.nextReleaseDate as string
    byDate.set(k, [...(byDate.get(k) ?? []), d])
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 bg-white/85 backdrop-blur border-b border-line">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center gap-2">
          <span className="text-lg">🍽</span>
          <span className="font-extrabold text-brand text-lg">订位提醒</span>
          <DataBadge status={status} />
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-5">
        <h1 className="text-2xl font-extrabold">难订餐厅 · {data.city}</h1>
        <p className="text-sm text-muted">按「放票时间表」算出下一个开放预订日。提前一天手机推送，要订就准点开抢。</p>

        <div className="mt-2 rounded-xl bg-canvas border border-line text-muted text-xs px-3 py-2 leading-relaxed">
          ℹ️ <b>定时放票</b>的日子标在日历上（如每月 1 号）；<b>滚动放票</b>的每天都在放 N 天后那一档，看「今天可订至」。
          放票<b>时间</b>未经官方核实的标「时间待确认」，不会自动推送——绝不编造时间提醒你。
        </div>

        <Calendar byDate={byDate} todayIso={data.today || TODAY} />

        <SectionTitle>即将放票 · {drops.length} 家</SectionTitle>
        <Card className="p-2 divide-y divide-line">
          {drops.length === 0 && <Empty />}
          {drops.map((r) => {
            const d = daysTo(r.nextReleaseDate as string)
            const soon = d <= 1
            return (
              <div key={r.id} className="p-3 flex items-start gap-3">
                <div className="w-14 shrink-0 text-center">
                  <div className="text-[11px] text-muted">{(r.nextReleaseDate as string).slice(5)}</div>
                  <div className={cx('text-[10px] font-bold', soon ? 'text-coral' : 'text-muted')}>
                    {d <= 0 ? '今天放' : `${d} 天后`}
                  </div>
                </div>
                <Body r={r} />
              </div>
            )
          })}
        </Card>

        <SectionTitle>滚动放票 · {rolling.length} 家</SectionTitle>
        <Card className="p-2 divide-y divide-line">
          {rolling.map((r) => (
            <div key={r.id} className="p-3 flex items-start gap-3">
              <div className="w-14 shrink-0 text-center">
                <div className="text-base font-bold tnum leading-none">{r.rollingDaysAhead ?? '—'}</div>
                <div className="text-[10px] text-muted">{r.rollingDaysAhead ? '天' : '待核实'}</div>
              </div>
              <Body r={r} />
            </div>
          ))}
        </Card>

        {unknown.length > 0 && (
          <>
            <SectionTitle>放票规律待确认 · {unknown.length} 家</SectionTitle>
            <Card className="p-2 divide-y divide-line">
              {unknown.map((r) => (
                <div key={r.id} className="p-3 flex items-start gap-3">
                  <div className="w-14 shrink-0 text-center text-[10px] text-muted pt-1">待确认</div>
                  <Body r={r} />
                </div>
              ))}
            </Card>
          </>
        )}

        <footer className="mt-10 mb-6 text-center text-[11px] text-muted">
          {data.generatedAt && <>数据更新于 {data.generatedAt.slice(0, 16).replace('T', ' ')} UTC · </>}
          自用原型 · 放票规则以官方为准
        </footer>
      </main>
    </div>
  )
}

function Body({ r }: { r: ReservationItem }) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-sm font-semibold">{r.name}</span>
        <Tag>{PLATFORM_LABEL[r.platform] ?? r.platform}</Tag>
        <Tag>{PREPAID_LABEL[r.prepaid]}</Tag>
        {!r.verifiedTime && r.model !== 'unknown' && <Tag tone="warn">时间待确认</Tag>}
        {r.confidence === 'low' && <Tag tone="warn">把握低</Tag>}
      </div>
      <div className="text-[11px] text-muted mt-0.5">{r.cuisine} · {r.priceNote}</div>
      {r.releaseLabel && <div className="text-[12px] mt-1 font-medium text-ink">{r.releaseLabel}</div>}
      <div className="text-[11px] text-muted mt-1 leading-snug">{r.notes}</div>
      <div className="mt-1.5 flex items-center gap-3">
        <a href={r.bookingUrl} target="_blank" rel="noreferrer" className="text-[12px] font-semibold text-brand hover:underline">去订位 ↗</a>
        <a href={r.source} target="_blank" rel="noreferrer" className="text-[11px] text-muted hover:underline">来源</a>
      </div>
    </div>
  )
}

function Tag({ children, tone = 'plain' }: { children: React.ReactNode; tone?: 'plain' | 'warn' }) {
  return (
    <span className={cx('text-[9px] font-bold px-1.5 py-0.5 rounded align-middle',
      tone === 'warn' ? 'bg-coral/10 text-coral' : 'bg-canvas border border-line text-muted')}>
      {children}
    </span>
  )
}

const Empty = () => <p className="text-center text-sm text-muted py-6">近期暂无确定放票日</p>

function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cx('rounded-2xl bg-white border border-line shadow-sm', className)}>{children}</div>
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center justify-between mb-3 mt-7"><h2 className="text-base font-bold">{children}</h2></div>
}

function DataBadge({ status }: { status: 'loading' | 'live' | 'fallback' }) {
  const meta = {
    loading: { label: '加载中…', cls: 'bg-canvas text-muted border-line', dot: 'bg-slate-400' },
    live: { label: '实时数据', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200', dot: 'bg-emerald-500' },
    fallback: { label: '本地兜底', cls: 'bg-amber-50 text-amber-600 border-amber-200', dot: 'bg-amber-500' },
  }[status]
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', meta.cls)}>
      <span className={cx('w-1.5 h-1.5 rounded-full', meta.dot)} />
      {meta.label}
    </span>
  )
}

// ---- 三个月日历：高亮有定时放票的日子 ----
function Calendar({ byDate, todayIso }: { byDate: Map<string, ReservationItem[]>; todayIso: string }) {
  const base = new Date(todayIso + 'T00:00:00')
  const months = [0, 1, 2].map((off) => new Date(base.getFullYear(), base.getMonth() + off, 1))
  return (
    <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
      {months.map((m) => (
        <MonthGrid key={m.toISOString()} month={m} byDate={byDate} todayIso={todayIso} />
      ))}
    </div>
  )
}

const WK = ['日', '一', '二', '三', '四', '五', '六']

function MonthGrid({ month, byDate, todayIso }: { month: Date; byDate: Map<string, ReservationItem[]>; todayIso: string }) {
  const year = month.getFullYear()
  const mon = month.getMonth()
  const firstDow = new Date(year, mon, 1).getDay()
  const days = new Date(year, mon + 1, 0).getDate()
  const cells: (number | null)[] = [...Array(firstDow).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)]

  return (
    <Card className="p-2.5">
      <div className="text-sm font-bold mb-1.5">{year} 年 {mon + 1} 月</div>
      <div className="grid grid-cols-7 gap-0.5 text-center">
        {WK.map((w) => <div key={w} className="text-[9px] text-muted py-0.5">{w}</div>)}
        {cells.map((day, i) => {
          if (day === null) return <div key={i} />
          const iso = `${year}-${String(mon + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
          const hits = byDate.get(iso)
          const isToday = iso === todayIso
          return (
            <div key={i}
              title={hits ? hits.map((h) => `${h.name} · ${h.releaseLabel}`).join('\n') : undefined}
              className={cx('aspect-square rounded-md flex flex-col items-center justify-center text-[11px] relative',
                isToday && 'ring-1 ring-brand',
                hits ? 'bg-brand-soft text-brand font-bold' : 'text-ink')}>
              <span>{day}</span>
              {hits && <span className="absolute bottom-0.5 w-1 h-1 rounded-full bg-brand" />}
            </div>
          )
        })}
      </div>
      {[...byDate.entries()]
        .filter(([k]) => k.startsWith(`${year}-${String(mon + 1).padStart(2, '0')}`))
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([k, list]) => (
          <div key={k} className="mt-1 text-[10px] text-muted leading-snug">
            <b className="text-brand">{k.slice(8)}日</b> {list.map((h) => h.name).join('、')}
          </div>
        ))}
    </Card>
  )
}
