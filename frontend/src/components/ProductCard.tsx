import type { Product } from '../lib/api'
import { money, timeAgo } from '../lib/format'
import { haptic } from '../lib/telegram'

interface Props {
  product: Product
  onOpen: (productId: number) => void
}

export function ProductCard({ product, onOpen }: Props) {
  const hasSale = Boolean(product.old_price && product.discount_percent)

  return (
    <button
      className="card"
      onClick={() => {
        haptic('light')
        onOpen(product.id)
      }}
    >
      {product.image_url ? (
        <img className="thumb" src={product.image_url} alt="" loading="lazy" />
      ) : (
        <div className="thumb thumb-empty">◻</div>
      )}

      <div className="card-body">
        <div className="brand">{product.brand ?? 'Золотое Яблоко'}</div>
        <div className="name">{product.name ?? `Товар ${product.item_id}`}</div>

        <div className="price-row">
          {product.in_stock ? (
            <>
              <span className={`price${hasSale ? ' sale' : ''}`}>
                {money(product.price)}
              </span>
              {hasSale && (
                <>
                  <span className="price-old">{money(product.old_price)}</span>
                  <span className="badge badge-sale">
                    −{product.discount_percent}%
                  </span>
                </>
              )}
            </>
          ) : (
            <span className="badge badge-out">нет в наличии</span>
          )}
        </div>
      </div>
    </button>
  )
}

export function CardMeta({ product }: { product: Product }) {
  const failed = Boolean(product.last_error)
  const stale =
    !failed &&
    product.last_success_at !== null &&
    Date.now() - new Date(product.last_success_at).getTime() > 6 * 3600 * 1000

  return (
    <div className="meta-line">
      <span className={`dot${failed ? ' err' : stale ? ' stale' : ''}`} />
      <span>
        {failed
          ? 'последняя проверка не удалась'
          : `обновлено ${timeAgo(product.last_success_at)}`}
      </span>
    </div>
  )
}
