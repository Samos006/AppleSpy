import { useEffect, useState } from 'react'
import { api, ApiError, type AppEvent, type Watch } from '../lib/api'
import { CardMeta, ProductCard } from '../components/ProductCard'
import { money, timeAgo } from '../lib/format'
import { haptic, notify } from '../lib/telegram'

interface Props {
  onOpen: (productId: number) => void
}

const EVENT_ICONS: Record<string, string> = {
  price_drop: '📉',
  price_rise: '📈',
  back_in_stock: '✅',
  out_of_stock: '⚠️',
  target_reached: '🎯',
}

const EVENT_TITLES: Record<string, string> = {
  price_drop: 'Цена снизилась',
  price_rise: 'Цена выросла',
  back_in_stock: 'Снова в наличии',
  out_of_stock: 'Закончился',
  target_reached: 'Цель достигнута',
}

export function ListPage({ onOpen }: Props) {
  const [watches, setWatches] = useState<Watch[] | null>(null)
  const [events, setEvents] = useState<AppEvent[]>([])
  const [url, setUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  async function load() {
    try {
      const [list, feed] = await Promise.all([api.listWatches(), api.events()])
      setWatches(list)
      setEvents(feed)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить список')
      setWatches([])
    }
  }

  async function handleAdd() {
    const value = url.trim()
    if (!value || adding) return

    setAdding(true)
    setError(null)
    try {
      const created = await api.addWatch(value)
      setUrl('')
      notify('success')
      await load()
      onOpen(created.product.id)
    } catch (e) {
      notify('error')
      setError(e instanceof ApiError ? e.message : 'Не удалось добавить товар')
    } finally {
      setAdding(false)
    }
  }

  return (
    <>
      <div className="header">
        <div className="header-row">
          <h1 className="logo">
            apple<span>spy</span>
          </h1>
          {watches && watches.length > 0 && (
            <span className="badge badge-lime">{watches.length} в слежке</span>
          )}
        </div>
        <p className="subtitle">Цены и наличие в Золотом Яблоке</p>
      </div>

      <div className="container">
        <div className="add-box">
          <input
            className="add-input"
            placeholder="Ссылка на товар ЗЯ"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            inputMode="url"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
          <button className="add-btn" onClick={handleAdd} disabled={adding || !url.trim()}>
            {adding ? <span className="spinner" /> : 'Следить'}
          </button>
        </div>
        {error ? (
          <div className="error-note">{error}</div>
        ) : (
          <div className="hint">
            Скопируйте адрес страницы товара — например
            goldapple.ru/19000116114-…
          </div>
        )}

        {watches === null && (
          <div className="card-list" style={{ marginTop: 22 }}>
            <div className="skeleton skeleton-card" />
            <div className="skeleton skeleton-card" />
            <div className="skeleton skeleton-card" />
          </div>
        )}

        {watches !== null && watches.length === 0 && (
          <div className="empty">
            <div className="empty-icon">🔍</div>
            <div className="empty-title">Пока пусто</div>
            <div className="empty-text">
              Пришлите ссылку на товар — и я сообщу, когда цена изменится
              или он вернётся в наличие.
            </div>
          </div>
        )}

        {watches !== null && watches.length > 0 && (
          <>
            {events.length > 0 && (
              <div className="section">
                <div className="eyebrow">Последние изменения</div>
                {events.slice(0, 5).map((event) => (
                  <div className="event-row" key={event.id}>
                    <div className="event-icon">{EVENT_ICONS[event.kind] ?? '🔔'}</div>
                    <div className="event-body">
                      <div className="event-title">
                        {event.product.brand ?? ''} {event.product.name ?? ''}
                      </div>
                      <div className="event-sub">
                        {EVENT_TITLES[event.kind] ?? 'Изменение'}
                        {event.new_value !== null && ` · ${money(event.new_value)}`}
                        {' · '}
                        {timeAgo(event.created_at)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="section">
              <div className="eyebrow">Отслеживаемые товары</div>
              <div className="card-list">
                {watches.map((watch) => (
                  <div key={watch.id}>
                    <ProductCard
                      product={watch.product}
                      onOpen={(id) => {
                        haptic('light')
                        onOpen(id)
                      }}
                    />
                    <CardMeta product={watch.product} />
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
