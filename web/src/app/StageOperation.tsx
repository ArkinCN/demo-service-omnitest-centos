import type { ReactNode } from 'react'
import { Button } from '../components/ui'

export function StageOperation({ title, status, children }: { title: string; status?: string; children: ReactNode }) {
  return <section className="stage-operation" aria-label={title}>
    <header><h4>{title}</h4>{status ? <span>{status}</span> : null}</header>
    {children}
  </section>
}

export function StageFooter({ label, onClick, disabled, reason, secondary }: {
  label: string; onClick?: () => void; disabled?: boolean; reason?: string; secondary?: ReactNode
}) {
  return <footer className="stage-operation-footer">
    <Button block size="lg" variant="primary" disabled={disabled || !onClick} onClick={onClick}>{label}</Button>
    {reason ? <p role="status">{reason}</p> : null}
    {secondary ? <div className="stage-operation-secondary">{secondary}</div> : null}
  </footer>
}
