import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function Button({ variant = 'secondary', className = '', type = 'button', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' }) {
  return <button type={type} className={`button button-${variant} ${className}`} {...props} />
}

export function Panel({ title, action, children, className = '' }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`} aria-label={title}>
    <div className="panel-heading"><h2>{title}</h2>{action}</div>{children}
  </section>
}

export function PageHeader({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <header className="page-heading"><div><h1>{title}</h1><p className="muted">{description}</p></div><div className="actions">{children}</div></header>
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><strong>{title}</strong><p className="muted">{children}</p></div>
}
