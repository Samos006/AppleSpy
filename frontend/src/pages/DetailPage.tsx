import { useEffect, useState } from 'react'
import { api, ApiError, type WatchDetail } from '../lib/api'
import { PriceChart } from '../components/PriceChart'
import { money, timeAgo } from '../lib/format'
import { haptic, notify } from '../lib/telegram'

interface Props {
  productId: number
  onBack: () => void
}

export function DetailPage({ productId, onBack }: Props) {
  const [data, setData] = useState<WatchDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [target, setTarget] = useState('')

  useEffect(() => {
    void load()
  }, [productId])

  async function load() {
    try {
      const detail = await api.watchDetail(productId)
      setData(detail)
      setTarget(detail.target_price ? String(Math.round(detail.target_price)) : '')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить товар')
    }
  }

  async function handleRefresh() {
    if (refreshing) return
    setRefreshing(true)
    haptic('medium')
    try {
      const fresh = await api.refresh(productId)
      setData(fresh)
      notify('success')
    } catch (e) {
      notify('error')
      setError(e instanceof ApiError ? e.message : 'Обновить не получилось')
    } finally {
      setRefreshing(false)
    }
  }

  async function toggle(field: 'notify_price_drop' | 'notify_price_rise' | 'notify_back_in_stock') {
    if (!data) return
    haptic('light')
    const next = !data[field]
    setData({ ...data, [field]: next })
    try {
      await api.updateWatch(productId, { [field]: next })
    } catch {
      setData({ ...data, [field]: !next })
    }
  }

  async function saveTarget() {
    if (!data) return
    const value = target.trim() === '' ? null : Number(target.replace(/\D/g, ''))
    if (value !== null && (Number.isNaN(value) || value <= 0)) return
    try {
      await api.updateWatch(productId, { target_price: value })
      setData({ ...data, target_price: value })
      notify('success')
    } catch {
      notify('error')
    }
  }

  async function handleDelete() {
    haptic('heavy')
    try {
      await api.deleteWatch(productId)
      onBack()
    } catch {
      notify('error')
    }
  }

  if (error) {
    return (
      <div className="container">
        <div className="empty">
          <div className="empty-icon">😕</div>
          <div className="empty-title">Не получилось</div>
          <div className="empty-text">{error}</div>
          <div className="btn-row">
            <button className="btn btn-ghost" onClick={onBack}>
              Назад
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="container" style={{ paddingTop: 16 }}>
        <div className="skeleton" style={{ height: 240 }} />
        <div className="skeleton" style={{ height: 90, marginTop: 12 }} />
        <div className="skeleton" style={{ height: 150, marginTop: 12 }} />
      </div>
    )
  }

  const p = data.product
  const hasSale = Boolean(p.old_price && p.discount_percent)
  const isLowest =
    p.price !== null && p.min_price !== null && p.price <= p.min_price

  return (
    <div className="container" style={{ paddingTop: 8 }}>
      <div className="hero">
        {p.image_url ? (
          <img src={p.image_url} alt={p.name ?? ''} />
        ) : (
          <div style={{ fontSize: 56, opacity: 0.25 }}>◻</div>
        )}
      </div>

      <div className="detail-brand">{p.brand ?? 'Золотое Яблоко'}</div>
      <h2 className="detail-name">{p.name ?? `Товар ${p.item_id}`}</h2>

      <div className="detail-price-row">
        {p.in_stock ? (
          <>
            <span className={`detail-price${hasSale ? ' sale' : ''}`}>
              {money(p.price)}
            </span>
            {hasSale && (
              <>
                <span className="detail-price-old">{money(p.old_price)}</span>
                <span className="badge badge-sale">−{p.discount_percent}%</span>
              </>
            )}
          </>
        ) : (
          <span className="badge badge-out">нет в наличии</span>
        )}
        {isLowest && p.in_stock && (
          <span className="badge badge-lime">минимум за всё время</span>
        )}
      </div>

      <div className="meta-line">
        <span className={`dot${p.last_error ? ' err' : ''}`} />
        <span>
          {p.last_error
            ? 'последняя проверка не удалась'
            : `обновлено ${timeAgo(p.last_success_at)}`}
        </span>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="stat-label">Минимум</div>
          <div className="stat-value">{money(p.min_price)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Максимум</div>
          <div className="stat-value">{money(p.max_price)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Замеров</div>
          <div className="stat-value">{data.history.length}</div>
        </div>
      </div>

      <div className="section">
        <div className="eyebrow">Динамика цены</div>
        <PriceChart history={data.history} />
      </div>

      <div className="btn-row">
        <button className="btn btn-ghost" onClick={handleRefresh}>
          {refreshing ? <span className="spinner" /> : 'Обновить сейчас'}
        </button>
      </div>

      <div className="section">
        <div className="eyebrow">Уведомления</div>

        <div className="setting">
          <div className="setting-text">
            <div className="setting-title">Снижение цены</div>
            <div className="setting-desc">Напишу, когда подешевеет</div>
          </div>
          <button
            className={`switch${data.notify_price_drop ? ' on' : ''}`}
            onClick={() => toggle('notify_price_drop')}
            aria-label="Уведомлять о снижении цены"
          />
        </div>

        <div className="setting">
          <div className="setting-text">
            <div className="setting-title">Рост цены</div>
            <div className="setting-desc">Обычно не нужно, но бывает полезно</div>
          </div>
          <button
            className={`switch${data.notify_price_rise ? ' on' : ''}`}
            onClick={() => toggle('notify_price_rise')}
            aria-label="Уведомлять о росте цены"
          />
        </div>

        <div className="setting">
          <div className="setting-text">
            <div className="setting-title">Появление в наличии</div>
            <div className="setting-desc">Как только товар вернётся</div>
          </div>
          <button
            className={`switch${data.notify_back_in_stock ? ' on' : ''}`}
            onClick={() => toggle('notify_back_in_stock')}
            aria-label="Уведомлять о появлении в наличии"
          />
        </div>
      </div>

      <div className="section">
        <div className="eyebrow">Целевая цена</div>
        <div className="setting-desc">
          Если задать, уведомление о снижении придёт только когда цена
          опустится до этой отметки.
        </div>
        <div className="target-row">
          <input
            className="target-input"
            inputMode="numeric"
            placeholder="Например, 3000"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
          <button className="btn btn-ghost" style={{ flex: '0 0 auto' }} onClick={saveTarget}>
            Сохранить
          </button>
        </div>
      </div>

      <div className="divider" />

      <div className="btn-row" style={{ marginBottom: 8 }}>
        <button className="btn btn-danger" onClick={handleDelete}>
          Перестать следить
        </button>
      </div>
    </div>
  )
}
