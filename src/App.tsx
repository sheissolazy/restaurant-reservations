import { useEffect, useMemo, useState } from 'react'
import { useJson } from './useJson'
import type { ReservationsData, ReservationItem } from './types'
import pushConfig from '../pipeline/favorites.json'

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

// ---- 收藏（星标）----
// 网页端星标存 localStorage（即时、按设备）；推送名单是仓库里的 favorites.json（构建时打包进来）。
// 二者不一致时给「同步推送名单」：复制 JSON + 跳 GitHub 编辑该文件，粘贴即让手机推送与星标一致。
const REPO = 'sheissolazy/restaurant-reservations'
const FAV_FILE = 'pipeline/favorites.json'
const FAV_EDIT_URL = `https://github.com/${REPO}/edit/main/${FAV_FILE}`
const FAV_COMMENT = (pushConfig as { _comment?: string })._comment ?? ''
const PUSH_LIST: string[] = (pushConfig as { favorites: string[] }).favorites ?? []
const LS_KEY = 'resv:favorites'

const loadFavs = (): string[] => {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as string[]) : [...PUSH_LIST]   // 首次访问 = 跟推送名单一致
  } catch { return [...PUSH_LIST] }
}
const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().join() === [...b].sort().join()

export default function App() {
  const { data, status } = useJson<ReservationsData>('reservations.json', EMPTY)
  const [favs, setFavs] = useState<string[]>(loadFavs)
  const [onlyFav, setOnlyFav] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(favs)) } catch { /* ignore */ }
  }, [favs])

  const isFav = (id: string) => favs.includes(id)
  const toggleFav = (id: string) =>
    setFavs((f) => (f.includes(id) ? f.filter((x) => x !== id) : [...f, id]))

  // 收藏排前：在每个分区里把星标的排到前面（稳定）
  const favFirst = (list: ReservationItem[]) =>
    [...list].sort((a, b) => Number(isFav(b.id)) - Number(isFav(a.id)))

  const visible = useMemo(
    () => (onlyFav ? data.items.filter((i) => favs.includes(i.id)) : data.items),
    [data.items, onlyFav, favs],
  )

  const drops = favFirst(visible.filter((i) => i.model === 'scheduled_drop' && i.nextReleaseDate))
  const rolling = favFirst(visible.filter((i) => i.model === 'rolling'))
  const unknown = favFirst(visible.filter((i) => i.model === 'unknown'))

  const byDate = new Map<string, ReservationItem[]>()
  for (const d of drops) {
    const k = d.nextReleaseDate as string
    byDate.set(k, [...(byDate.get(k) ?? []), d])
  }

  // 推送名单同步：本地星标 vs 仓库 favorites.json
  const pushSynced = sameSet(favs, PUSH_LIST)
  const favsCanPush = data.items.filter((i) => favs.includes(i.id) && i.verifiedTime)
  const syncPushList = async () => {
    const json = JSON.stringify({ _comment: FAV_COMMENT, favorites: favs }, null, 2) + '\n'
    try { await navigator.clipboard.writeText(json); setCopied(true); setTimeout(() => setCopied(false), 2500) } catch { /* ignore */ }
    window.open(FAV_EDIT_URL, '_blank', 'noopener')
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 bg-white/85 backdrop-blur border-b border-line">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center gap-2">
          <span className="text-lg">🍽</span>
          <span className="font-extrabold text-brand text-lg">订位提醒</span>
          <DataBadge status={status} />
          <button
            onClick={() => setOnlyFav((v) => !v)}
            className={cx('ml-auto text-xs font-semibold rounded-full border px-2.5 py-1',
              onlyFav ? 'bg-amber/10 text-amber border-amber/40' : 'bg-canvas text-muted border-line')}>
            {onlyFav ? '★ 只看收藏' : '☆ 全部'}
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-5">
        <h1 className="text-2xl font-extrabold">难订餐厅 · {data.city}</h1>
        <p className="text-sm text-muted">点 ☆ 收藏。提前一天手机推送——只推你收藏的餐厅。</p>

        <div className="mt-2 rounded-xl bg-canvas border border-line text-muted text-xs px-3 py-2 leading-relaxed">
          ℹ️ <b>定时放票</b>的日子标在日历上（如每月 1 号）；<b>滚动放票</b>的每天都在放 N 天后那一档，看「今天可订至」。
          放票<b>时间</b>未经官方核实的标「时间待确认」，不会自动推送——绝不编造时间提醒你。
        </div>

        {/* 推送名单同步条 */}
        {!pushSynced && (
          <div className="mt-3 rounded-xl bg-amber/10 border border-amber/40 text-ink text-xs px-3 py-2.5 flex items-start gap-2">
            <span className="text-amber font-bold">⟳</span>
            <div className="flex-1">
              <div className="font-semibold">星标已改，手机推送名单还没同步</div>
              <div className="text-muted mt-0.5">推送在云端跑、读不到本机星标。点右侧把名单复制并到 GitHub 粘贴提交，手机推送就会与星标一致。</div>
            </div>
            <button onClick={syncPushList}
              className="shrink-0 self-center text-xs font-bold rounded-lg bg-brand text-white px-3 py-1.5 hover:opacity-90">
              {copied ? '已复制 ✓' : '同步推送名单'}
            </button>
          </div>
        )}
        {pushSynced && favs.length > 0 && (
          <div className="mt-3 text-[11px] text-muted">
            🔔 已收藏 {favs.length} 家 · 其中可推送（放票时间已核实）：
            {favsCanPush.length ? favsCanPush.map((r) => r.name).join('、') : '暂无'}
          </div>
        )}

        <Calendar byDate={byDate} todayIso={data.today || TODAY} />

        <SectionTitle>即将放票 · {drops.length} 家</SectionTitle>
        <Card className="p-2 divide-y divide-line">
          {drops.length === 0 && <Empty onlyFav={onlyFav} />}
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
                <Body r={r} fav={isFav(r.id)} onToggle={toggleFav} />
              </div>
            )
          })}
        </Card>

        {rolling.length > 0 && (
          <>
            <SectionTitle>滚动放票 · {rolling.length} 家</SectionTitle>
            <Card className="p-2 divide-y divide-line">
              {rolling.map((r) => (
                <div key={r.id} className="p-3 flex items-start gap-3">
                  <div className="w-14 shrink-0 text-center">
                    <div className="text-base font-bold tnum leading-none">{r.rollingDaysAhead ?? '—'}</div>
                    <div className="text-[10px] text-muted">{r.rollingDaysAhead ? '天' : '待核实'}</div>
                  </div>
                  <Body r={r} fav={isFav(r.id)} onToggle={toggleFav} />
                </div>
              ))}
            </Card>
          </>
        )}

        {unknown.length > 0 && (
          <>
            <SectionTitle>放票规律待确认 · {unknown.length} 家</SectionTitle>
            <Card className="p-2 divide-y divide-line">
              {unknown.map((r) => (
                <div key={r.id} className="p-3 flex items-start gap-3">
                  <div className="w-14 shrink-0 text-center text-[10px] text-muted pt-1">待确认</div>
                  <Body r={r} fav={isFav(r.id)} onToggle={toggleFav} />
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

function Body({ r, fav, onToggle }: { r: ReservationItem; fav: boolean; onToggle: (id: string) => void }) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-1.5 flex-wrap">
        <button onClick={() => onToggle(r.id)} aria-label={fav ? '取消收藏' : '收藏'}
          className={cx('text-base leading-none -ml-0.5 mr-0.5', fav ? 'text-amber' : 'text-line hover:text-amber')}>
          {fav ? '★' : '☆'}
        </button>
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

const Empty = ({ onlyFav }: { onlyFav?: boolean }) =>
  <p className="text-center text-sm text-muted py-6">{onlyFav ? '收藏里近期暂无确定放票日' : '近期暂无确定放票日'}</p>

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
