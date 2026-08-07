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

export default function TelemetryGrid({ current, history, loading, error }: TelemetryGridProps) {
  if (error) {
    return (
      <div className="bg-slate-900/40 border border-rose-700/50 rounded-lg p-8 text-center">
        <AlertTriangle className="w-8 h-8 text-rose-400 mx-auto mb-3" />
        <p className="text-rose-300 font-mono">{error}</p>
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
        <h2 className="text-lg font-bold text-slate-100 font-mono">Live metrics</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-5 animate-pulse">
              <div className="h-40 bg-slate-800 rounded mb-4" />
              <div className="h-4 bg-slate-800 rounded w-1/2" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!hasMetrics || !current) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-bold text-slate-100 font-mono">Live metrics</h2>
        <p className="text-sm text-slate-400 font-mono border border-slate-700/50 rounded-lg p-5">
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
      <h2 className="text-lg font-bold text-slate-100 font-mono">Live metrics</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-5 hover:border-slate-600/50 transition-colors">
          <div className="mb-4">
            <p className="text-slate-300 text-sm font-mono">Network Throughput</p>
            <div className="flex items-baseline gap-2 mt-1 flex-wrap">
              <p className="text-2xl font-bold text-emerald-400 font-mono">
                {current.network_throughput_in.toFixed(2)}
              </p>
              <p className="text-slate-400 text-sm font-mono">Mbps In</p>
              <p className="text-xl font-bold text-slate-300 font-mono ml-2">
                {current.network_throughput_out.toFixed(2)}
              </p>
              <p className="text-slate-400 text-sm font-mono">Mbps Out</p>
            </div>
            <p className={`text-xs font-mono mt-2 flex items-center gap-1 ${isHighThroughput ? 'text-amber-400' : 'text-emerald-400'}`}>
              {throughputTrend !== '—' && (throughputTrend.startsWith('+') ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />)}
              {throughputTrend} vs prior sample
            </p>
          </div>
          <div className="w-full" style={{ height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={throughputData}>
              <defs>
                <linearGradient id="colorIn" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.8} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorOut" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#64748b" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#64748b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '4px' }}
                formatter={(value) => (typeof value === 'number' ? `${value.toFixed(2)} Mbps` : value)}
              />
              <Area type="monotone" dataKey="in" stroke="#10b981" fillOpacity={1} fill="url(#colorIn)" />
              <Area type="monotone" dataKey="out" stroke="#64748b" fillOpacity={1} fill="url(#colorOut)" />
            </AreaChart>
          </ResponsiveContainer>
          </div>
        </div>

        <div
          className={`rounded-lg p-5 border transition-colors ${
            isHighJitter
              ? 'bg-rose-950/30 border-rose-700/50 hover:border-rose-600/50'
              : 'bg-slate-900/40 border-slate-700/50 hover:border-slate-600/50'
          }`}
        >
          <div className="mb-4">
            <p className={`text-sm font-mono ${isHighJitter ? 'text-rose-300' : 'text-slate-300'}`}>Link Jitter</p>
            <div className="flex items-baseline gap-2 mt-1">
              <p className={`text-2xl font-bold font-mono ${isHighJitter ? 'text-rose-400' : 'text-emerald-400'}`}>
                {current.link_jitter.toFixed(2)}
              </p>
              <p className={`text-sm font-mono ${isHighJitter ? 'text-rose-400' : 'text-slate-400'}`}>ms</p>
            </div>
            <p className={`text-xs font-mono mt-2 ${isHighJitter ? 'text-rose-400' : 'text-slate-400'}`}>
              {jitterTrend} vs prior sample
            </p>
          </div>
          <div className="w-full" style={{ height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={jitterData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '4px' }}
                formatter={(value) => (typeof value === 'number' ? value.toFixed(2) : value)}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={isHighJitter ? '#f43f5e' : '#10b981'}
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-5 hover:border-slate-600/50 transition-colors">
          <div className="mb-4">
            <p className="text-slate-300 text-sm font-mono">Packet Health</p>
            <p className={`text-2xl font-bold font-mono mt-1 ${isHighPacketLoss ? 'text-rose-400' : 'text-emerald-400'}`}>
              {packetHealth.toFixed(1)}%
            </p>
            <p className={`text-xs font-mono mt-1 ${isHighPacketLoss ? 'text-rose-400' : 'text-slate-400'}`}>
              Loss: {current.packet_loss.toFixed(2)}%
            </p>
          </div>
          <div className="mb-4">
            <div className="w-full h-3 bg-slate-800 rounded-full overflow-hidden border border-slate-700">
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
          <p className={`text-xs font-mono ${isHighPacketLoss ? 'text-rose-400' : 'text-emerald-400'}`}>
            {isHighPacketLoss ? `${current.packet_loss.toFixed(2)}% loss from backend` : 'Within expected range'}
          </p>
        </div>

        <div
          className={`rounded-lg p-5 border transition-colors ${
            isHighPathLatency || isHighRouting
              ? 'bg-rose-950/30 border-rose-700/50 hover:border-rose-600/50'
              : 'bg-slate-900/40 border-slate-700/50 hover:border-slate-600/50'
          }`}
        >
          <div className="mb-4">
            <p
              className={`text-sm font-mono ${
                isHighPathLatency || isHighRouting ? 'text-rose-300' : 'text-slate-300'
              }`}
            >
              Path latency
            </p>
            <div className="flex items-baseline gap-2 mt-1 flex-wrap">
              <p
                className={`text-2xl font-bold font-mono ${
                  isHighPathLatency ? 'text-rose-400' : 'text-emerald-400'
                }`}
              >
                {greNow.toFixed(2)}
              </p>
              <p className="text-slate-400 text-sm font-mono">ms GRE</p>
              <p className="text-xl font-bold text-slate-300 font-mono ml-2">{ethNow.toFixed(2)}</p>
              <p className="text-slate-400 text-sm font-mono">ms backup</p>
            </div>
            <p
              className={`text-xs font-mono mt-1 ${
                isHighRouting ? 'text-rose-400' : 'text-slate-400'
              }`}
            >
              {isHighRouting
                ? `Routing flaps ${current.routing_updates.toFixed(2)}/s`
                : 'Primary vs backup RTT — spikes mean path trouble'}
            </p>
          </div>
          <div className="w-full" style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={routingData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
                <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #475569',
                    borderRadius: '4px',
                  }}
                  formatter={(value) =>
                    typeof value === 'number' ? `${value.toFixed(2)} ms` : value
                  }
                />
                <Line
                  type="monotone"
                  dataKey="gre"
                  name="GRE"
                  stroke={isHighPathLatency ? '#f43f5e' : '#10b981'}
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="eth0"
                  name="Backup"
                  stroke="#64748b"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
