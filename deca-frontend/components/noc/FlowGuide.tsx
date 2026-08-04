'use client'

type Step = { n: string; title: string; body: string; hot?: boolean }

export default function FlowGuide({ actionableCount }: { actionableCount: number }) {
  const steps: Step[] = [
    {
      n: '01',
      title: 'Watch',
      body: 'Sites + underlay health from the live operator / Prometheus.',
    },
    {
      n: '02',
      title: 'Analyze',
      body: 'Model raises land here as alerts (congestion, tunnel, BGP, drift…).',
      hot: actionableCount > 0,
    },
    {
      n: '03',
      title: 'Ask',
      body: 'Responder narrates analyzer values only — no invented topology.',
    },
    {
      n: '04',
      title: 'Approve',
      body: 'You gate the steer. Approve writes audit, then steers GRE↔eth0.',
      hot: actionableCount > 0,
    },
  ]

  return (
    <section className="deca-flow" aria-label="How to use DECA">
      <p className="deca-flow-label">How to read this screen</p>
      <ol className="deca-flow-steps">
        {steps.map((s, i) => (
          <li key={s.n} className={`deca-flow-step${s.hot ? ' is-hot' : ''}`}>
            <span className="deca-flow-n">{s.n}</span>
            <div>
              <p className="deca-flow-title">{s.title}</p>
              <p className="deca-flow-body">{s.body}</p>
            </div>
            {i < steps.length - 1 ? <span className="deca-flow-arrow" aria-hidden /> : null}
          </li>
        ))}
      </ol>
    </section>
  )
}
