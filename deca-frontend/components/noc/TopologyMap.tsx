'use client'

import { useMemo } from 'react'
import type { AlertRow, FleetSite, MissionState, TopologyLayout } from '@/lib/api'

function siteTick(sites: FleetSite[], id: string) {
  return sites.find((s) => s.id === id)?.hosts_state?.[0]
}

function isAlert(sites: FleetSite[], id: string) {
  const c = siteTick(sites, id)?.confirmed
  return Boolean(c && c !== 'healthy' && c !== '—' && c !== 'none')
}

function nodeOnline(
  sites: FleetSite[],
  node: LayoutNode,
): boolean {
  if (node.muted) return false
  const fleetId = node.fleet_id || node.id
  if (isAlert(sites, fleetId)) return false
  // PE / chaos without fleet rows stay up unless muted
  if (node.kind === 'pe' || node.kind === 'chaos') return true
  const site = sites.find((s) => s.id === fleetId)
  if (site && site.status === 'alert') return false
  return true
}

type LiveEvent = { tone: 'ok' | 'warn' | 'accent' | 'mute'; text: string }

function buildEvents(
  mission: MissionState | null,
  sites: FleetSite[],
  alerts: AlertRow[],
  recentAction: { action: string; alert_id: number | null; ts: string } | null | undefined,
  fabric: string,
): LiveEvent[] {
  const out: LiveEvent[] = []
  const path = (mission?.active_path || '').toLowerCase()
  const gre = path === 'gre' || path === 'gre-te-core'
  const human = mission?.human_override

  out.push({
    tone: 'mute',
    text: `Fabric · ${fabric === 'gns3' ? 'GNS3 sim (NOC-driven)' : 'Pi live stations'}`,
  })

  if (human) {
    out.push({
      tone: 'accent',
      text: `Human gate holding underlay → ${human} (autonomy suspended)`,
    })
  } else {
    out.push({
      tone: 'ok',
      text: gre
        ? 'Autonomous steer on gre-te-core · mission underlay via CORE'
        : path === 'eth0'
          ? 'Autonomous steer on eth0 backup (OSPF 50)'
          : 'Underlay path unknown',
    })
  }

  if (mission?.conflict) {
    out.push({
      tone: 'warn',
      text: `Policy conflict: TT&C wants ${mission.ttc_wanted || '?'} · Payload wants ${mission.payload_wanted || '?'} → TT&C wins`,
    })
  }

  const lat = mission?.path_latency_ms
  if (lat?.gre != null || lat?.eth0 != null) {
    out.push({
      tone: 'mute',
      text: `Probe RTT  gre ${lat.gre != null ? `${lat.gre.toFixed(2)} ms` : '—'}  ·  eth0 ${lat.eth0 != null ? `${lat.eth0.toFixed(2)} ms` : '—'}`,
    })
  }

  for (const a of alerts.slice(0, 3)) {
    if (a.status !== 'active') continue
    if (!a.class || ['healthy', 'advisory_clear', 'confirmed_clear'].includes(a.class)) continue
    // When fabric is GNS3, skip Pi station* rows; when Pi, skip gns3-*
    if (fabric === 'gns3' && String(a.host || '').startsWith('station')) continue
    if (fabric === 'pi' && String(a.host || '').startsWith('gns3')) continue
    out.push({
      tone: 'warn',
      text: `Analyzer ${a.event || 'event'}: ${a.class} @ ${a.host || '?'}`,
    })
  }

  for (const s of sites) {
    if (isAlert(sites, s.id)) {
      const t = siteTick(sites, s.id)
      out.push({
        tone: 'warn',
        text: `${s.name}: ${t?.confirmed || 'alert'}`,
      })
    }
  }

  if (recentAction) {
    out.push({
      tone: recentAction.action === 'approve' ? 'accent' : 'mute',
      text: `Dashboard ${recentAction.action} alert #${recentAction.alert_id} · ${recentAction.ts}`,
    })
  }

  return out.slice(0, 10)
}

type LayoutNode = NonNullable<TopologyLayout['nodes']>[number]

const ICON = 40

function nodeCenter(n: LayoutNode) {
  // Layout boxes → icon center (GNS3-style compact glyph)
  return { x: n.x + n.w / 2, y: n.y + Math.min(n.h, ICON + 8) / 2 }
}

function linkEndpoints(from: LayoutNode, to: LayoutNode, curve?: string) {
  const a = nodeCenter(from)
  const b = nodeCenter(to)
  if (curve === 'bottom') {
    const midY = Math.max(a.y, b.y) + 90
    return {
      a,
      b,
      d: `M ${a.x} ${a.y} C ${a.x} ${midY}, ${b.x} ${midY}, ${b.x} ${b.y}`,
      mid: { x: (a.x + b.x) / 2, y: midY - 24 },
    }
  }
  if (curve === 'top') {
    const midY = Math.min(a.y, b.y) - 70
    return {
      a,
      b,
      d: `M ${a.x} ${a.y} C ${a.x} ${midY}, ${b.x} ${midY}, ${b.x} ${b.y}`,
      mid: { x: (a.x + b.x) / 2, y: midY + 18 },
    }
  }
  return {
    a,
    b,
    d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`,
    mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
  }
}

/** Point along a straight segment, inset from each end toward the other. */
function insetToward(
  from: { x: number; y: number },
  to: { x: number; y: number },
  dist: number,
) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const len = Math.hypot(dx, dy) || 1
  const t = Math.min(dist / len, 0.45)
  return { x: from.x + dx * t, y: from.y + dy * t }
}

function linkIsUp(fromUp: boolean, toUp: boolean): boolean {
  // GNS3-style: green = both ends up; red = either end down / muted / alert
  return fromUp && toUp
}

function NodeGlyph({
  node,
  online,
}: {
  node: LayoutNode
  online: boolean
}) {
  const c = nodeCenter(node)
  const kind = node.kind || 'ce'
  const half = ICON / 2
  const labelY = c.y + half + 14

  return (
    <g className={`gns-node kind-${kind}${online ? ' is-up' : ' is-down'}${node.muted ? ' is-muted' : ''}`}>
      {/* tower / appliance silhouette */}
      <rect
        x={c.x - half}
        y={c.y - half}
        width={ICON}
        height={ICON}
        rx={4}
        className="gns-icon-bg"
      />
      <rect x={c.x - 10} y={c.y - 14} width={20} height={26} rx={2} className="gns-icon-body" />
      <rect x={c.x - 7} y={c.y - 10} width={14} height={3} className="gns-icon-slot" />
      <rect x={c.x - 7} y={c.y - 4} width={14} height={3} className="gns-icon-slot" />
      <rect x={c.x - 7} y={c.y + 2} width={14} height={3} className="gns-icon-slot" />
      <circle cx={c.x + 6} cy={c.y + 10} r={1.6} className="gns-icon-led" />
      {/* node status LED (GNS3 summary light) */}
      <circle
        cx={c.x + half - 2}
        cy={c.y - half + 2}
        r={4.5}
        className={online ? 'gns-led-up' : 'gns-led-down'}
      />
      <text x={c.x} y={labelY} textAnchor="middle" className="gns-label">
        {node.label}
      </text>
      {node.sub ? (
        <text x={c.x} y={labelY + 12} textAnchor="middle" className="gns-sub">
          {node.sub}
        </text>
      ) : null}
    </g>
  )
}

function CaptureLens({ x, y }: { x: number; y: number }) {
  return (
    <g className="gns-pcap" transform={`translate(${x}, ${y})`} style={{ pointerEvents: 'none' }}>
      <circle r={7} className="gns-pcap-ring" />
      <circle r={3.5} className="gns-pcap-lens" />
      <line x1={5} y1={5} x2={9} y2={9} className="gns-pcap-handle" />
    </g>
  )
}

export default function TopologyMap({
  sites,
  mission,
  alerts = [],
  recentAction = null,
  fabric = 'pi',
  layout = null,
  onCaptureLink,
  captureBusy = false,
  captureMessage = null,
}: {
  sites: FleetSite[]
  mission: MissionState | null
  alerts?: AlertRow[]
  recentAction?: { action: string; alert_id: number | null; ts: string } | null
  fabric?: string
  layout?: TopologyLayout | null
  onCaptureLink?: (link: {
    link_id: string
    from_id: string
    to_id: string
  }) => void
  captureBusy?: boolean
  captureMessage?: string | null
}) {
  const path = (mission?.active_path || '').toLowerCase()
  const greOn = path === 'gre' || path === 'gre-te-core'
  const ethOn = path === 'eth0'
  const human = mission?.human_override
  const conflict = Boolean(mission?.conflict)
  const events = useMemo(
    () => buildEvents(mission, sites, alerts, recentAction, fabric),
    [mission, sites, alerts, recentAction, fabric],
  )

  const nodes = layout?.nodes || []
  const links = layout?.links || []
  const frames = layout?.frames || []
  const byId = useMemo(() => {
    const m = new Map<string, LayoutNode>()
    for (const n of nodes) m.set(n.id, n)
    return m
  }, [nodes])

  const onlineById = useMemo(() => {
    const m = new Map<string, boolean>()
    for (const n of nodes) m.set(n.id, nodeOnline(sites, n))
    return m
  }, [nodes, sites])

  const vb = layout?.viewBox || [0, 0, 1100, 600]
  const viewBox = `${vb[0]} ${vb[1]} ${vb[2]} ${vb[3]}`

  const upCount = [...onlineById.values()].filter(Boolean).length
  const linkStats = useMemo(() => {
    let up = 0
    let down = 0
    for (const lnk of links) {
      const from = byId.get(lnk.from)
      const to = byId.get(lnk.to)
      if (!from || !to) continue
      const ok = linkIsUp(
        onlineById.get(lnk.from) ?? false,
        onlineById.get(lnk.to) ?? false,
      )
      if (ok) up += 1
      else down += 1
    }
    return { up, down }
  }, [links, byId, onlineById])

  return (
    <section className="deca-panel">
      <div className="deca-panel-head">
        <div>
          <h2 className="deca-section-title">Site topology</h2>
          <p className="deca-section-sub">
            {layout?.subtitle ||
              (fabric === 'gns3'
                ? 'GNS3 canvas · drive from NOC (GUI optional)'
                : 'Pi as-built · single CORE · gre-te + eth0 backup')}
            {' · '}
            <strong>click a link</strong> to open Wireshark
          </p>
        </div>
        <div className="deca-path-badge">
          <span className="deca-field-label">
            {human ? 'Human override' : 'Active underlay'}
          </span>
          <strong className="font-mono text-[var(--deca-accent)] text-lg">
            {human || (greOn ? 'gre-te-core' : ethOn ? 'eth0' : path || '—')}
          </strong>
          <span className="text-[10px] text-[var(--deca-mute)]">
            {fabric.toUpperCase()}
            {conflict ? ' · conflict · TT&C wins' : ' · classes agree'}
            {human ? ' · autonomy suspended' : ''}
          </span>
        </div>
      </div>

      <div className={`deca-live-topo is-schematic${conflict ? ' has-conflict' : ''}${human ? ' has-human' : ''}`}>
        <svg
          viewBox={viewBox}
          className="deca-live-svg"
          role="img"
          aria-label={`${fabric} SD-WAN topology`}
        >
          {frames.map((f, i) => (
            <g key={`frame-${i}`} className="gns-station">
              <rect
                x={f.x}
                y={f.y}
                width={f.w}
                height={f.h}
                rx={6}
                className={`gns-station-box${f.core ? ' core' : ''}`}
              />
              <text x={f.x + 12} y={f.y + 18} className="gns-station-label">
                {f.label}
              </text>
            </g>
          ))}

          {links.map((lnk) => {
            const from = byId.get(lnk.from)
            const to = byId.get(lnk.to)
            if (!from || !to) return null
            const ep = linkEndpoints(from, to, lnk.curve)
            const fromUp = onlineById.get(lnk.from) ?? false
            const toUp = onlineById.get(lnk.to) ?? false
            const up = linkIsUp(fromUp, toUp)
            const kind = lnk.kind || 'attach'
            const carrying =
              (kind === 'gre' && greOn) ||
              (kind === 'eth0' && ethOn) ||
              kind === 'ipsec'
            const clickable = Boolean(onCaptureLink)
            const aDot = insetToward(ep.a, ep.b, ICON / 2 + 2)
            const bDot = insetToward(ep.b, ep.a, ICON / 2 + 2)
            return (
              <g
                key={lnk.id}
                className={`gns-link kind-${kind}${up ? ' is-up' : ' is-down'}${carrying ? ' is-carrying' : ''}`}
                style={clickable ? { cursor: captureBusy ? 'wait' : 'pointer' } : undefined}
                onClick={
                  clickable
                    ? () =>
                        onCaptureLink?.({
                          link_id: lnk.id,
                          from_id: lnk.from,
                          to_id: lnk.to,
                        })
                    : undefined
                }
              >
                {clickable ? (
                  <path
                    d={ep.d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth={16}
                    style={{ pointerEvents: 'stroke' }}
                  >
                    <title>
                      {up ? 'UP' : 'DOWN'}
                      {carrying ? ' · ACTIVE underlay' : ''}
                      {' · Open Wireshark on '}
                      {lnk.label || lnk.id}
                    </title>
                  </path>
                ) : null}
                <path
                  d={ep.d}
                  fill="none"
                  className="gns-wire"
                  style={{ pointerEvents: clickable ? 'none' : undefined }}
                />
                {/* GNS3-style interface status squares */}
                <rect
                  x={aDot.x - 4}
                  y={aDot.y - 4}
                  width={8}
                  height={8}
                  className={up ? 'gns-port-up' : 'gns-port-down'}
                  style={{ pointerEvents: 'none' }}
                />
                <rect
                  x={bDot.x - 4}
                  y={bDot.y - 4}
                  width={8}
                  height={8}
                  className={up ? 'gns-port-up' : 'gns-port-down'}
                  style={{ pointerEvents: 'none' }}
                />
                {clickable ? <CaptureLens x={ep.mid.x} y={ep.mid.y} /> : null}
                {lnk.label && (kind === 'gre' || kind === 'eth0' || kind === 'ipsec') ? (
                  <text
                    x={ep.mid.x}
                    y={ep.mid.y - (clickable ? 12 : 6)}
                    textAnchor="middle"
                    className="gns-edge-label"
                    style={{ pointerEvents: 'none' }}
                  >
                    {lnk.label}
                    {up ? (carrying ? ' · ACTIVE' : ' · UP') : ' · DOWN'}
                  </text>
                ) : null}
              </g>
            )
          })}

          {nodes.map((n) => (
            <NodeGlyph key={n.id} node={n} online={onlineById.get(n.id) ?? false} />
          ))}

          {conflict ? (
            <g className="live-conflict">
              <rect x={vb[2] / 2 - 190} y={vb[3] - 36} width={380} height={28} rx={4} />
              <text x={vb[2] / 2} y={vb[3] - 17} textAnchor="middle">
                sdwan_policy_conflict=1 · TT&C dictates underlay
              </text>
            </g>
          ) : null}
        </svg>
      </div>

      <div className="deca-live-events">
        <p className="deca-field-label">Live actions on this fabric</p>
        {captureMessage ? (
          <p className="deca-section-sub font-mono text-[11px] mb-2">
            Capture: {captureMessage}
          </p>
        ) : null}
        <ul>
          {events.map((e, i) => (
            <li key={`${e.text}-${i}`} className={`tone-${e.tone}`}>
              <span className="dot" />
              {e.text}
            </li>
          ))}
        </ul>
      </div>

      <div className="deca-topo-legend-row">
        <span>
          <i className="swatch led-up" /> Node / link UP
        </span>
        <span>
          <i className="swatch led-down" /> Node / link DOWN
        </span>
        <span>
          {upCount}/{nodes.length} nodes · {linkStats.up} up / {linkStats.down} down links
        </span>
        <span>Magnifier = click for Wireshark</span>
      </div>
    </section>
  )
}
