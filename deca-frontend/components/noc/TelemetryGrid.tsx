'use client'

import {
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { AlertTriangle, TrendingDown, TrendingUp } from 'lucide-react'
import { MetricsSnapshot } from '@/lib/telemetry-context'

interface TelemetryGridProps {
  current: MetricsSnapshot | null
  history: MetricsSnapshot[]
  loading: boolean
  error: string | null
}

function pctChange(series: number[]): string {
  if (series.length < 2) return '—'
  const prev = series[series.length - 2]
  const curr = series[series.length - 1]
  if (prev === 0) return '—'
  const delta = ((curr - prev) / Math.abs(prev)) * 100
  const sign = delta >= 0 ? '+' : ''
  return `${sign}${delta.toFixed(1)}%`
}

const card =
  'rounded-lg p-5 border border-[var(--deca-line)] bg-[var(--deca-panel)] transition-colors'
const title = 'text-lg font-bold text-[var(--deca-ink)] font-mono'
const label = 'text-sm font-mono text-[var(--deca-mute)]'
const value = 'text-2xl font-bold font-mono text-[var(--deca-ink)]'
const tipStyle = {
  backgroundColor: '#ffffff',
  border: '1px solid #cbd5e1',
  borderRadius: '4px',
  color: '#0f172a',
}

export default function TelemetryGrid({ current, history, loading, error }: TelemetryGridProps) {
  if (error) {
    return (
      <div className="border border-[var(--deca-warn)]/40 bg-rose-50 rounded-lg p-8 text-center">
        <AlertTriangle className="w-8 h-8 text-[var(--deca-warn)] mx-auto mb-3" />
        <p className="text-[var(--deca-warn)] font-mono">{error}</p>
      </div>
    )
  }

  const hasMetrics =
    current != null &&
    typeof current.network_throughput_in === 'number' &&
    typeof current.link_jitter === 'number' &&
    typeof current.packet_loss === 'number'

  if (loading && !hasMetrics) {
    return (
      <div className="space-y-4">
        <h2 className={title}>Live metrics</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className={`${card} animate-pulse`}>
              <div className="h-40 bg-[var(--deca-panel-2)] rounded mb-4" />
              <div className="h-4 bg-[var(--deca-panel-2)] rounded w-1/2" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!hasMetrics || !current) {
    return (
      <div className="space-y-4">
        <h2 className={title}>Live metrics</h2>
        <p className="text-sm text-[var(--deca-mute)] font-mono border border-[var(--deca-line)] rounded-lg p-5 bg-[var(--deca-panel)]">
          Waiting for Prometheus samples (throughput, jitter, loss). Fleet map above still updates.
        </p>
      </div>
    )
  }

  const series = history.length > 0 ? history : [current]
  const throughputData = series.map((m, idx) => ({
    time: idx + 1,
    in: Number(m.network_throughput_in) || 0,
    out: Number(m.network_throughput_out) || 0,
  }))

  const jitterData = series.map((m, idx) => ({
    time: idx + 1,
    value: Number(m.link_jitter) || 0,
  }))

  const routingData = series.map((m, idx) => ({
    time: idx + 1,
    gre: Number(m.latency_gre_ms ?? 0) || 0,
    eth0: Number(m.latency_eth0_ms ?? 0) || 0,
    updates: Number(m.routing_updates) || 0,
  }))

  const throughputSeries = series.map((m) => m.network_throughput_in)
  const jitterSeries = series.map((m) => m.link_jitter)
  const greNow = Number(current.latency_gre_ms ?? 0) || 0
  const ethNow = Number(current.latency_eth0_ms ?? 0) || 0
  const pathLatency = Math.max(greNow, ethNow)
  const isHighPathLatency = pathLatency > 25
  const isHighRouting = current.routing_updates > 2

  const isHighThroughput = current.network_throughput_in > 100
  const isHighJitter = current.link_jitter > 10
  const isHighPacketLoss = current.packet_loss > 2
  const packetHealth = Math.max(0, 100 - current.packet_loss)

  const throughputTrend = pctChange(throughputSeries)
  const jitterTrend = pctChange(jitterSeries)

  return (
    <div className="space-y-4">
      <h2 className={title}>Live metrics</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className={card}>
          <div className="mb-4">
            <p className={label}>Network Throughput</p>
            <div className="flex items-baseline gap-2 mt-1 flex-wrap">
              <p className={`${value} text-[var(--deca-ok)]`}>
                {current.network_throughput_in.toFixed(2)}
              </p>
              <p className={label}>Mbps In</p>
              <p className="text-xl font-bold text-[var(--deca-ink)] font-mono ml-2">
                {current.network_throughput_out.toFixed(2)}
              </p>
              <p className={label}>Mbps Out</p>
            </div>
            <p
              className={`text-xs font-mono mt-2 flex items-center gap-1 ${
                isHighThroughput ? 'text-amber-600' : 'text-[var(--deca-ok)]'
              }`}
            >
              {throughputTrend !== '—' &&
                (throughputTrend.startsWith('+') ? (
                  <TrendingUp className="w-3 h-3" />
                ) : (
                  <TrendingDown className="w-3 h-3" />
                ))}
              {throughputTrend} vs prior sample
            </p>
          </div>
          <div className="w-full" style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={throughputData}>
                <defs>
                  <linearGradient id="colorIn" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#059669" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#059669" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorOut" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#64748b" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#64748b" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
                <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
                <Tooltip
                  contentStyle={tipStyle}
                  formatter={(value) =>
                    typeof value === 'number' ? `${value.toFixed(2)} Mbps` : value
                  }
                />
                <Area type="monotone" dataKey="in" stroke="#059669" fillOpacity={1} fill="url(#colorIn)" />
                <Area type="monotone" dataKey="out" stroke="#64748b" fillOpacity={1} fill="url(#colorOut)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div
          className={`${card} ${
            isHighJitter ? 'border-[var(--deca-warn)]/50 bg-rose-50' : ''
          }`}
        >
          <div className="mb-4">
            <p className={`${label} ${isHighJitter ? 'text-[var(--deca-warn)]' : ''}`}>Link Jitter</p>
            <div className="flex items-baseline gap-2 mt-1">
              <p
                className={`${value} ${
                  isHighJitter ? 'text-[var(--deca-warn)]' : 'text-[var(--deca-ok)]'
                }`}
              >
                {current.link_jitter.toFixed(2)}
              </p>
              <p className={label}>ms</p>
            </div>
            <p className={`text-xs font-mono mt-2 ${isHighJitter ? 'text-[var(--deca-warn)]' : label}`}>
              {jitterTrend} vs prior sample
            </p>
          </div>
          <div className="w-full" style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={jitterData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
                <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
                <Tooltip contentStyle={tipStyle} formatter={(value) => (typeof value === 'number' ? value.toFixed(2) : value)} />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={isHighJitter ? '#dc2626' : '#059669'}
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className={card}>
          <div className="mb-4">
            <p className={label}>Packet Health</p>
            <p
              className={`${value} mt-1 ${
                isHighPacketLoss ? 'text-[var(--deca-warn)]' : 'text-[var(--deca-ok)]'
              }`}
            >
              {packetHealth.toFixed(1)}%
            </p>
            <p className={`text-xs font-mono mt-1 ${isHighPacketLoss ? 'text-[var(--deca-warn)]' : label}`}>
              Loss: {current.packet_loss.toFixed(2)}%
            </p>
          </div>
          <div className="mb-4">
            <div className="w-full h-3 bg-[var(--deca-panel-2)] rounded-full overflow-hidden border border-[var(--deca-line)]">
              <div
                className={`h-full transition-all duration-500 ${
                  isHighPacketLoss
                    ? 'bg-gradient-to-r from-rose-500 to-rose-600'
                    : 'bg-gradient-to-r from-emerald-500 to-emerald-600'
                }`}
                style={{ width: `${packetHealth}%` }}
              />
            </div>
          </div>
          <p className={`text-xs font-mono ${isHighPacketLoss ? 'text-[var(--deca-warn)]' : 'text-[var(--deca-ok)]'}`}>
            {isHighPacketLoss
              ? `${current.packet_loss.toFixed(2)}% loss from backend`
              : 'Within expected range'}
          </p>
        </div>

        <div
          className={`${card} ${
            isHighPathLatency || isHighRouting ? 'border-[var(--deca-warn)]/50 bg-rose-50' : ''
          }`}
        >
          <div className="mb-4">
            <p
              className={`${label} ${
                isHighPathLatency || isHighRouting ? 'text-[var(--deca-warn)]' : ''
              }`}
            >
              Path latency
            </p>
            <div className="flex items-baseline gap-2 mt-1 flex-wrap">
              <p
                className={`${value} ${
                  isHighPathLatency ? 'text-[var(--deca-warn)]' : 'text-[var(--deca-ok)]'
                }`}
              >
                {greNow.toFixed(2)}
              </p>
              <p className={label}>ms GRE</p>
              <p className="text-xl font-bold text-[var(--deca-ink)] font-mono ml-2">{ethNow.toFixed(2)}</p>
              <p className={label}>ms backup</p>
            </div>
            <p className={`text-xs font-mono mt-1 ${isHighRouting ? 'text-[var(--deca-warn)]' : label}`}>
              {isHighRouting
                ? `Routing flaps ${current.routing_updates.toFixed(2)}/s`
                : 'Primary vs backup RTT — spikes mean path trouble'}
            </p>
          </div>
          <div className="w-full" style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={routingData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
                <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
                <Tooltip
                  contentStyle={tipStyle}
                  formatter={(value) =>
                    typeof value === 'number' ? `${value.toFixed(2)} ms` : value
                  }
                />
                <Line
                  type="monotone"
                  dataKey="gre"
                  name="GRE"
                  stroke={isHighPathLatency ? '#dc2626' : '#059669'}
                  dot={false}
                  strokeWidth={2}
                />
                <Line type="monotone" dataKey="eth0" name="Backup" stroke="#64748b" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
