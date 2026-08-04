'use client'

import {
  AreaChart,
  Area,
  LineChart,
  Line,
  BarChart,
  Bar,
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
    typeof current.link_jitter === 'number'

  if (loading || !hasMetrics) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-bold text-slate-100 font-mono">Telemetry Matrix</h2>
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-5 animate-pulse">
                <div className="h-40 bg-slate-800 rounded mb-4" />
                <div className="h-4 bg-slate-800 rounded w-1/2" />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400 font-mono border border-slate-700/50 rounded-lg p-5">
            Prom telemetry unavailable in orchestrator light mode. Fleet / TT&C panels above still live.
            Set <span className="text-emerald-400">DECA_HEAVY_INIT=1</span> on the API for the full matrix.
          </p>
        )}
      </div>
    )
  }

  const throughputData = history.map((m, idx) => ({
    time: idx,
    in: m.network_throughput_in,
    out: m.network_throughput_out,
  }))

  const jitterData = history.map((m, idx) => ({
    time: idx,
    value: m.link_jitter,
  }))

  const routingData = history.map((m, idx) => ({
    time: idx,
    updates: m.routing_updates,
  }))

  const throughputSeries = history.map((m) => m.network_throughput_in)
  const jitterSeries = history.map((m) => m.link_jitter)

  const isHighThroughput = current.network_throughput_in > 100
  const isHighJitter = current.link_jitter > 10
  const isHighPacketLoss = current.packet_loss > 2
  const isHighRouting = current.routing_updates > 10
  const packetHealth = Math.max(0, 100 - current.packet_loss)

  const throughputTrend = pctChange(throughputSeries)
  const jitterTrend = pctChange(jitterSeries)

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold text-slate-100 font-mono">Telemetry Matrix</h2>

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
          <ResponsiveContainer width="100%" height={180}>
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
          <ResponsiveContainer width="100%" height={180}>
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

        <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-5 hover:border-slate-600/50 transition-colors">
          <div className="mb-4">
            <p className="text-slate-300 text-sm font-mono">Routing Stability</p>
            <p className={`text-2xl font-bold font-mono mt-1 ${isHighRouting ? 'text-rose-400' : 'text-emerald-400'}`}>
              {current.routing_updates.toFixed(2)}
            </p>
            <p className="text-slate-400 text-xs font-mono mt-1">BGP updates/sec (aggregated)</p>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={routingData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '4px' }}
                formatter={(value) => (typeof value === 'number' ? value.toFixed(2) : value)}
              />
              <Bar dataKey="updates" fill={isHighRouting ? '#f43f5e' : '#10b981'} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
