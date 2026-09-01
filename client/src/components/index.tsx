
import { AlertTriangle, Info,  } from 'lucide-react';
import type { CapabilityState } from '../types/badminton';

export function Panel({ children, className = '' }: { children: React.ReactNode, className?: string }) {
  return (
    <div className={`border border-line bg-panel p-4 ${className}`}>
      {children}
    </div>
  );
}

export function SectionHeader({ eyebrow, title, chip, description }: { eyebrow: string, title: string, chip?: string, description?: string }) {
  return (
    <div className="mb-6 border-b border-line pb-4">
      <div className="flex items-center gap-3 mb-2">
        <span className="font-mono text-xs uppercase tracking-wider text-muted">{eyebrow}</span>
        {chip && <span className="px-2 py-0.5 bg-ink border border-line text-[10px] font-mono text-muted uppercase tracking-wider">{chip}</span>}
      </div>
      <h2 className="font-display text-2xl uppercase tracking-widest text-paper mb-2">{title}</h2>
      {description && <p className="font-body text-sm text-muted max-w-3xl leading-relaxed">{description}</p>}
    </div>
  );
}

export function ContractChip({ state, label }: { state: CapabilityState, label?: string }) {
  let color = 'text-muted border-line';
  let dot = 'bg-muted';
  
  if (state === 'available') {
    color = 'text-acid border-acid/30';
    dot = 'bg-acid';
  } else if (state === 'partial' || state === 'withheld') {
    color = 'text-amber border-amber/30';
    dot = 'bg-amber';
  } else if (state === 'error' || state === 'unavailable') {
    color = 'text-danger border-danger/30';
    dot = 'bg-danger';
  }

  return (
    <div className={`inline-flex items-center gap-2 px-2 py-1 border bg-ink ${color} text-xs font-mono uppercase tracking-wider`}>
      <span>{label || state}</span>
      <div className={`w-1.5 h-1.5 rounded-full ${dot}`} />
    </div>
  );
}

export function ReadinessCard({ title, state, reason }: { title: string, state: CapabilityState, reason?: string }) {
  let stateColor = 'text-muted';
  let dotColor = 'bg-muted';

  if (state === 'available') {
    stateColor = 'text-acid';
    dotColor = 'bg-acid';
  } else if (state === 'partial' || state === 'withheld') {
    stateColor = 'text-amber';
    dotColor = 'bg-amber';
  } else if (state === 'error' || state === 'unavailable') {
    stateColor = 'text-danger';
    dotColor = 'bg-danger';
  }

  return (
    <div className="border border-line bg-panel p-4 flex flex-col h-full">
      <span className="font-mono text-xs uppercase tracking-wider text-muted mb-4">{title}</span>
      <div className="mt-auto flex items-center justify-between">
        <span className={`font-mono text-xs uppercase tracking-wider ${stateColor}`}>
          {state === 'available' ? 'Live' : (state === 'withheld' ? 'Held' : state)}
        </span>
        <div className={`w-2 h-2 rounded-full ${dotColor}`} />
      </div>
      {reason && state !== 'available' && (
        <div className="mt-2 text-[10px] font-mono text-muted border-t border-line/50 pt-2 break-words">
          {reason}
        </div>
      )}
    </div>
  );
}

export function ProviderError({ reason, state = 'error' }: { reason: string, state?: CapabilityState }) {
  return (
    <div className="border border-line bg-panel p-4 mb-4">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 text-danger" />
        <span className="font-mono text-xs uppercase text-danger tracking-wider">Provider capability {state}</span>
      </div>
      <p className="text-sm font-mono text-muted break-words">{reason}</p>
    </div>
  );
}

export function PathButton({ onClick, children }: { onClick?: () => void, children: React.ReactNode }) {
  return (
    <button onClick={onClick} className="w-full text-left p-4 border border-line bg-ink hover:bg-panel-strong transition-colors group flex items-center justify-between">
      <span className="font-mono text-sm uppercase tracking-wider text-paper group-hover:text-acid transition-colors">{children}</span>
      <span className="text-muted group-hover:text-acid">→</span>
    </button>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="p-8 border border-line border-dashed bg-ink flex flex-col items-center justify-center text-center">
      <Info className="w-6 h-6 text-muted mb-3 opacity-50" />
      <span className="font-mono text-xs text-muted uppercase tracking-wider">{message}</span>
    </div>
  );
}
