interface TrendlineChartProps {
  data: number[]
  isWarning: boolean
}

export default function TrendlineChart({ data, isWarning }: TrendlineChartProps) {
  const maxValue = Math.max(...data)
  const minValue = Math.min(...data)
  const range = maxValue - minValue || 1

  // Create SVG path for the sparkline
  const points = data.map((value, idx) => {
    const x = (idx / (data.length - 1)) * 100
    const y = 100 - ((value - minValue) / range) * 100
    return `${x},${y}`
  })

  const pathData = `M ${points.join(' L ')}`
  const strokeColor = isWarning ? '#f43f5e' : '#10b981'
  const fillColor = isWarning ? 'rgba(244, 63, 94, 0.1)' : 'rgba(16, 185, 129, 0.1)'

  return (
    <div className="w-full h-full">
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="w-full h-full"
      >
        {/* Grid lines */}
        <line x1="0" y1="50" x2="100" y2="50" stroke="#334155" strokeWidth="0.5" opacity="0.3" />
        
        {/* Fill area under curve */}
        <path
          d={`${pathData} L 100,100 L 0,100 Z`}
          fill={fillColor}
          opacity="0.5"
        />
        
        {/* Main line */}
        <path
          d={pathData}
          fill="none"
          stroke={strokeColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        
        {/* Data points */}
        {points.map((point, idx) => {
          const [x, y] = point.split(',').map(Number)
          return (
            <circle
              key={idx}
              cx={x}
              cy={y}
              r="1.5"
              fill={strokeColor}
              opacity={idx === data.length - 1 ? 1 : 0.4}
            />
          )
        })}
      </svg>
    </div>
  )
}
