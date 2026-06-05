export type ResPlatform = 'tock' | 'opentable' | 'sevenrooms' | 'resy' | 'phone'
export type ResModel = 'scheduled_drop' | 'rolling' | 'unknown'

export interface ReservationItem {
  id: string
  name: string
  cuisine: string
  city: string
  platform: ResPlatform
  bookingUrl: string
  priceNote: string
  prepaid: 'full' | 'deposit' | 'none' | 'unknown'
  model: ResModel
  confidence: 'high' | 'medium' | 'low'
  verifiedTime: boolean        // 放票「时间点」是否核实；false → 显示「时间待确认」
  notes: string
  source: string
  // 计算字段（由放票规则推出）
  nextReleaseDate: string | null
  nextReleaseAt: string | null
  releaseLabel: string | null
  opensInDays: number | null
  rollingDaysAhead: number | null
  bookableThrough: string | null
}

export interface ReservationsData {
  generatedAt: string
  today: string
  city: string
  items: ReservationItem[]
}
