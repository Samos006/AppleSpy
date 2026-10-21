interface TgWebApp {
  initData: string
  initDataUnsafe: { user?: { id: number; first_name?: string; username?: string } }
  colorScheme: 'light' | 'dark'
  themeParams: Record<string, string>
  viewportStableHeight: number
  ready(): void
  expand(): void
  close(): void
  openLink(url: string, options?: { try_instant_view?: boolean }): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  disableVerticalSwipes?(): void
  BackButton: {
    show(): void
    hide(): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
  }
  HapticFeedback: {
    impactOccurred(style: 'light' | 'medium' | 'heavy'): void
    notificationOccurred(type: 'error' | 'success' | 'warning'): void
    selectionChanged(): void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp: TgWebApp }
  }
}

export const tg = (): TgWebApp | undefined => window.Telegram?.WebApp

export const isTelegram = (): boolean => Boolean(tg()?.initData)

export function initTelegram(): void {
  const app = tg()
  if (!app) return
  app.ready()
  app.expand()

  app.disableVerticalSwipes?.()
  try {
    app.setHeaderColor('#ffffff')
  } catch {}
}

export function haptic(style: 'light' | 'medium' | 'heavy' = 'light'): void {
  try {
    tg()?.HapticFeedback.impactOccurred(style)
  } catch {}
}

export function notify(type: 'error' | 'success' | 'warning'): void {
  try {
    tg()?.HapticFeedback.notificationOccurred(type)
  } catch {}
}

export function openExternal(url: string): void {
  const app = tg()
  if (app) app.openLink(url)
  else window.open(url, '_blank', 'noopener')
}

export function useBackButton(visible: boolean, onBack: () => void): void {
  const app = tg()
  if (!app) return
  if (visible) {
    app.BackButton.onClick(onBack)
    app.BackButton.show()
  } else {
    app.BackButton.hide()
    app.BackButton.offClick(onBack)
  }
}
