import React, { useEffect, useState } from 'react';
import { Panel, SectionHeader, ReadinessCard, ProviderError, ContractChip, PathButton } from '../components';
import { fetchHealth, fetchCalendar, fetchModelContract } from '../api';
import type { ProviderHealth, CalendarEntry, CapabilityState } from '../types/badminton';
import { useNavigate } from 'react-router-dom';

export function CommandDesk() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<{data: ProviderHealth | null, state: CapabilityState}>({ data: null, state: 'loading' });
  const [calendar, setCalendar] = useState<{data: CalendarEntry[] | null, state: CapabilityState}>({ data: null, state: 'loading' });
  const [model, setModel] = useState<{data: any, state: CapabilityState}>({ data: null, state: 'loading' });

  useEffect(() => {
    fetchHealth().then(res => setHealth(res));
    fetchCalendar().then(res => setCalendar(res));
    fetchModelContract().then(res => setModel(res));
  }, []);

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="BWF Supercomputer / Command desk" 
        title="THE MATCH IS MORE THAN A PICK." 
        description="An evidence-bounded badminton intelligence system. Every surface resolves independently so an unavailable live feed cannot conceal verified official calendar evidence." 
      />

      <div className="flex flex-col md:flex-row gap-4 mb-8">
        <button onClick={() => navigate('/matches')} className="px-6 py-2 bg-acid text-ink font-mono uppercase tracking-wider text-sm hover:bg-paper transition-colors font-bold">Open Match Centre</button>
        <button onClick={() => navigate('/methodology')} className="px-6 py-2 bg-ink border border-line text-paper font-mono uppercase tracking-wider text-sm hover:bg-panel-strong transition-colors">Inspect Methodology</button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <ReadinessCard 
          title="Official calendar" 
          state={calendar.state === 'available' ? 'available' : (calendar.state === 'loading' ? 'loading' : 'withheld')} 
          reason={calendar.data ? `${calendar.data.length} verified entries` : 'Awaiting sync'} 
        />
        <ReadinessCard 
          title="Forecast model" 
          state={model.data?.model?.available ? 'available' : 'withheld'} 
          reason={model.data?.model?.reason || 'Awaiting validation'} 
        />
        <ReadinessCard 
          title="Predictions" 
          state={model.data?.predictions?.available ? 'available' : 'withheld'} 
          reason={model.data?.predictions?.reason || 'No published predictions'} 
        />
        <ReadinessCard 
          title="Draw topology" 
          state={model.data?.topology?.available ? "available" : "withheld"}
          reason={model.data?.topology?.reason || "Gate until direct PDF validation and canonical reconciliation are complete."} 
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-8">
        <Panel className="col-span-1 lg:col-span-2">
          <h3 className="font-mono text-xs uppercase text-acid tracking-wider mb-4 pb-2 border-b border-line">Provider Observability</h3>
          {health.state === 'available' && health.data ? (
            <div className="space-y-3 font-mono text-xs text-muted">
              <div className="flex justify-between border-b border-line/50 pb-2"><span className="uppercase">API Health</span><span className="text-paper">{health.data.apiStatus}</span></div>
              <div className="flex justify-between border-b border-line/50 pb-2"><span className="uppercase">Database Health</span><span className="text-paper">{health.data.databaseStatus}</span></div>
              <div className="flex justify-between border-b border-line/50 pb-2"><span className="uppercase">Calendar Snapshot</span><span className="text-paper">{health.data.latestDataTimestamp}</span></div>
              <div className="flex justify-between border-b border-line/50 pb-2"><span className="uppercase">Live Matches</span><span className="text-acid">{health.data.liveMatchCount}</span></div>
              <div className="flex justify-between border-b border-line/50 pb-2"><span className="uppercase">Issues (24h)</span><span className={health.data.errorsLast24Hours > 0 ? 'text-amber' : 'text-paper'}>{health.data.errorsLast24Hours}</span></div>
              <div className="mt-4 p-2 bg-ink border border-line text-[10px] uppercase">Telemetry isolated. Calendar data preserves verified state independently.</div>
            </div>
          ) : (
            <ProviderError state={health.state} reason="Health telemetry is currently unavailable or isolated." />
          )}
        </Panel>
        
        <div className="space-y-4">
           <h3 className="font-mono text-xs uppercase text-paper tracking-wider pb-2 border-b border-line">Operational Pathways</h3>
           <PathButton onClick={() => navigate('/matches')}>Search the senior match slate</PathButton>
           <PathButton onClick={() => navigate('/tournaments')}>Trace official calendar records</PathButton>
           <PathButton onClick={() => navigate('/accuracy')}>Read the honesty ledger</PathButton>
        </div>
      </div>

      <div className="mt-8">
        <h3 className="font-mono text-xs uppercase text-paper tracking-wider mb-4 pb-2 border-b border-line">Official calendar signal: Next approved events</h3>
        {calendar.state === 'loading' ? (
           <p className="font-mono text-xs text-muted uppercase">Resolving calendar...</p>
        ) : calendar.state === 'available' && calendar.data ? (
           <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
             {calendar.data.slice(0, 4).map((ev: CalendarEntry) => (
               <Panel key={ev.sourceTournamentId}>
                 <div className="flex justify-between items-start mb-2">
                   <h4 className="font-display uppercase text-lg text-paper">{ev.name}</h4>
                   <ContractChip state="available" label="Eligible" />
                 </div>
                 <p className="font-body text-xs text-muted mb-1">{ev.category}</p>
                 <p className="font-mono text-[10px] text-muted">{ev.startDate} to {ev.endDate}</p>
               </Panel>
             ))}
           </div>
        ) : (
           <ProviderError state={calendar.state} reason="No validated official calendar response is currently available." />
        )}
      </div>

      <Panel className="mt-8 bg-panel-strong border-line-bright/30">
        <h3 className="font-mono text-xs uppercase text-acid tracking-wider mb-2">Model governance: Forecast boundary</h3>
        <p className="font-body text-sm text-muted">
          Probability, confidence, contributor lists, and uncertainty appear only when the provider publishes a matching pre-match snapshot for a validated eligible match.
        </p>
      </Panel>
    </div>
  );
}
