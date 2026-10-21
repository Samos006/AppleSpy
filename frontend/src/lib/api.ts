import { tg } from './telegram'

export interface Product {
  id: number
  item_id: string
  url: string
  name: string | null
  brand: string | null
  image_url: string | null
  variant: string | null
  price: number | null
  old_price: number | null
  in_stock: boolean
  rating: number | null
  reviews_count: number | null
  last_checked_at: string | null
  last_success_at: string | null
  last_error: string | null
  discount_percent: number | null
  min_price: number | null
  max_price: number | null
}

export interface PricePoint {
  price: number | null
  old_price: number | null
  in_stock: boolean
  captured_at: string
}

export interface Watch {
  id: number
  product: Product
  notify_price_drop: boolean
  notify_price_rise: boolean
  notify_back_in_stock: boolean
  target_price: number | null
  created_at: string
}

export interface WatchDetail extends Watch {
  history: PricePoint[]
}

export interface AppEvent {
  id: number
  kind: string
  old_value: number | null
  new_value: number | null
  created_at: string
  product: Product
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const initData = tg()?.initData ?? ''

  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',

      Authorization: `tma ${initData}`,
      'X-Init-Data': initData,
      ...(init.headers ?? {}),
    },
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `Ошибка ${response.status}`
    throw new ApiError(detail, response.status)
  }

  return payload as T
}

export const api = {
  me: () => request<{ tg_id: number; first_name: string | null; watches_count: number }>('/me'),

  listWatches: () => request<Watch[]>('/watches'),

  addWatch: (url: string) =>
    request<WatchDetail>('/watches', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  watchDetail: (productId: number) => request<WatchDetail>(`/watches/${productId}`),

  updateWatch: (productId: number, patch: Partial<Pick<Watch, 'notify_price_drop' | 'notify_price_rise' | 'notify_back_in_stock' | 'target_price'>>) =>
    request<Watch>(`/watches/${productId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deleteWatch: (productId: number) =>
    request<void>(`/watches/${productId}`, { method: 'DELETE' }),

  refresh: (productId: number) =>
    request<WatchDetail>(`/watches/${productId}/refresh`, { method: 'POST' }),

  events: () => request<AppEvent[]>('/events'),
}
