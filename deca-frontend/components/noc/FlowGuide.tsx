'use client'

type Step = { n: string; title: string; body: string; hot?: boolean }

export default function FlowGuide({
  actionableCount,
  faultRunning = false,
  hasCopilot = false,
}: {
  actionableCount: number
  faultRunning?: boolean
  hasCopilot?: boolean
}) {
  const steps: Step[] = [
    {
      n: '1',
      title: 'Inject a problem',
      body: 'In Lab controls, click one Simple fault (rain fade, CPU stress, …).',
      hot: faultRunning && actionableCount === 0,
    },
    {
      n: '2',
      title: 'Model predicts',
      body: 'A Decide card appears with what is failing and when SLA will break.',
      hot: actionableCount > 0,
    },
    {
      n: '3',
      title: 'Copilot explains',
      body: 'Plain-language root cause and what an operator should check next.',
      hot: hasCopilot || (actionableCount > 0 && !faultRunning),
    },
    {
      n: '4',
      title: 'Approve or wait',
      body: 'Approve steers to backup and stops the inject. Reject declines the steer but also stops the inject. Then wait — telemetry settles to healthy naturally.',
      hot: actionableCount > 0,
    },
  ]

  return (
    <section className="deca-flow" aria-label="How this demo works">
      <p className="deca-flow-label">Jury walkthrough — 4 steps</p>
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
