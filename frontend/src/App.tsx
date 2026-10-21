import { useCallback, useEffect, useState } from 'react'
import { ListPage } from './pages/ListPage'
import { DetailPage } from './pages/DetailPage'
import { api, type Watch } from './lib/api'
import { haptic, openExternal, tg } from './lib/telegram'

const GA_HOME = 'https://goldapple.ru/'

function initialProductId(): number | null {
  const params = new URLSearchParams(window.location.search)
  const raw = params.get('product')
  if (raw && /^\d+$/.test(raw)) return Number(raw)

  const startParam = tg()?.initDataUnsafe as unknown as { start_param?: string }
  const start = startParam?.start_param
  if (start && /^\d+$/.test(start)) return Number(start)

  return null
}

export default function App() {
  const [productId, setProductId] = useState<number | null>(initialProductId)
  const [footerUrl, setFooterUrl] = useState<string>(GA_HOME)

  const goBack = useCallback(() => {
    setProductId(null)
    setFooterUrl(GA_HOME)
    window.history.replaceState({}, '', '/')
  }, [])

  const openProduct = useCallback((id: number) => {
    setProductId(id)
    window.history.replaceState({}, '', `/?product=${id}`)
  }, [])

  useEffect(() => {
    const app = tg()
    if (!app) return

    if (productId === null) {
      app.BackButton.hide()
      return
    }

    app.BackButton.onClick(goBack)
    app.BackButton.show()
    return () => {
      app.BackButton.offClick(goBack)
      app.BackButton.hide()
    }
  }, [productId, goBack])

  useEffect(() => {
    if (productId === null) {
      setFooterUrl(GA_HOME)
      return
    }
    let cancelled = false
    api
      .watchDetail(productId)
      .then((detail: Watch) => {
        if (!cancelled) setFooterUrl(detail.product.url)
      })
      .catch(() => {
        if (!cancelled) setFooterUrl(GA_HOME)
      })
    return () => {
      cancelled = true
    }
  }, [productId])

  return (
    <div className="app">
      {productId === null ? (
        <ListPage onOpen={openProduct} />
      ) : (
        <DetailPage productId={productId} onBack={goBack} />
      )}

      <div className="footer">
        <button
          className="footer-btn"
          onClick={() => {
            haptic('medium')
            openExternal(footerUrl)
          }}
        >
          Открыть в ЗЯ
        </button>
      </div>
    </div>
  )
}
