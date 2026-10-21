import { useMemo } from 'react'
import type { PricePoint } from '../lib/api'
import { moneyShort, shortDate } from '../lib/format'

interface Props {
  history: PricePoint[]
  height?: number
}

const PAD_X = 10
const PAD_TOP = 18
const PAD_BOTTOM = 20
const WIDTH = 320

export function PriceChart({ history, height = 150 }: Props) {
  const points = useMemo(
    () => history.filter((p): p is PricePoint & { price: number } => p.price !== null),
    [history],
  )

  const geometry = useMemo(() => {
    if (points.length === 0) return null

    const prices = points.map((p) => p.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)

    const span = max - min || Math.max(max * 0.08, 1)
    const top = max + span * 0.18
    const bottom = min - span * 0.18

    const innerW = WIDTH - PAD_X * 2
    const innerH = height - PAD_TOP - PAD_BOTTOM

    const x = (index: number) =>
      points.length === 1
        ? PAD_X + innerW / 2
        : PAD_X + (index / (points.length - 1)) * innerW

    const y = (price: number) =>
      PAD_TOP + innerH - ((price - bottom) / (top - bottom)) * innerH

    const coords = points.map((p, i) => ({ x: x(i), y: y(p.price), point: p }))

    let line = `M ${coords[0].x} ${coords[0].y}`
    for (let i = 1; i < coords.length; i += 1) {
      line += ` L ${coords[i].x} ${coords[i - 1].y} L ${coords[i].x} ${coords[i].y}`
    }
    if (coords.length === 1) {
      line += ` L ${WIDTH - PAD_X} ${coords[0].y}`
    }

    const lastX = coords.length === 1 ? WIDTH - PAD_X : coords[coords.length - 1].x
    const area = `${line} L ${lastX} ${PAD_TOP + innerH} L ${coords[0].x} ${
      PAD_TOP + innerH
    } Z`

    return { coords, line, area, min, max, minY: y(min), maxY: y(max) }
  }, [points, height])

  if (!geometry) {
    return (
      <div className="chart-wrap">
        <div className="chart-empty">
          История пока пустая.
          <br />
          Первые точки появятся после нескольких проверок.
        </div>
      </div>
    )
  }

  const { coords, line, area, min, max, minY, maxY } = geometry
  const last = coords[coords.length - 1]
  const first = points[0]
  const isDown = points.length > 1 && last.point.price < points[0].price

  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label="Динамика цены"
      >
        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="0%"
              stopColor={isDown ? '#2f9e44' : '#c8df34'}
              stopOpacity="0.28"
            />
            <stop
              offset="100%"
              stopColor={isDown ? '#2f9e44' : '#c8df34'}
              stopOpacity="0"
            />
          </linearGradient>
        </defs>

        {}
        <line
          x1={PAD_X}
          y1={maxY}
          x2={WIDTH - PAD_X}
          y2={maxY}
          stroke="currentColor"
          strokeOpacity="0.12"
          strokeDasharray="3 4"
        />
        <line
          x1={PAD_X}
          y1={minY}
          x2={WIDTH - PAD_X}
          y2={minY}
          stroke="currentColor"
          strokeOpacity="0.12"
          strokeDasharray="3 4"
        />

        <path d={area} fill="url(#priceFill)" />
        <path
          d={line}
          fill="none"
          stroke={isDown ? '#2f9e44' : '#101010'}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {}
        {coords
          .filter((c) => !c.point.in_stock)
          .map((c, i) => (
            <circle
              key={`out-${i}`}
              cx={c.x}
              cy={c.y}
              r="3"
              fill="var(--bg-soft)"
              stroke="#e5484d"
              strokeWidth="1.5"
            />
          ))}

        <circle
          cx={last.x}
          cy={last.y}
          r="4.5"
          fill={isDown ? '#2f9e44' : '#101010'}
          stroke="var(--bg-soft)"
          strokeWidth="2.5"
        />

        <text
          x={PAD_X}
          y={maxY - 5}
          fontSize="10"
          fill="currentColor"
          opacity="0.5"
          fontWeight="600"
        >
          {moneyShort(max)}
        </text>
        <text
          x={PAD_X}
          y={minY + 12}
          fontSize="10"
          fill="currentColor"
          opacity="0.5"
          fontWeight="600"
        >
          {moneyShort(min)}
        </text>
      </svg>

      <div className="chart-legend">
        <span>{shortDate(first.captured_at)}</span>
        <span>
          {points.length} {points.length === 1 ? 'замер' : 'замеров'}
        </span>
        <span>{shortDate(last.point.captured_at)}</span>
      </div>
    </div>
  )
}
