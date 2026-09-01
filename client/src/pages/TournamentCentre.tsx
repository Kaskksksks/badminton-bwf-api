import React, { useEffect, useState } from 'react';
import { SectionHeader, ProviderError, Panel, ContractChip } from '../components';
import { fetchCalendar } from '../api';
import type { CalendarEntry, CapabilityState } from '../types/badminton';

export function TournamentCentre() {
  const [calendar, setCalendar] = useState<{data: CalendarEntry[] | null, state: CapabilityState}>({ data: null, state: 'loading' });

  useEffect(() => {
    fetchCalendar().then(res => setCalendar(res));
  }, []);

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="Verified tournament calendar" 
        title="Tournament centre" 
        chip="Corporate calendar / read only"
        description="These cards are sourced from eligible BWF Corporate calendar records, with direct document metadata and calendar snapshot provenance. Dates and venue are never inferred from other sources." 
      />

      <div className="flex gap-4 border-b border-line mb-6">
        <button className="px-4 py-2 border-b-2 border-acid text-acid font-mono text-sm uppercase tracking-wider">Upcoming events</button>
        <button className="px-4 py-2 text-muted hover:text-paper font-mono text-sm uppercase tracking-wider">All events</button>
      </div>

      {calendar.state === 'loading' ? (
        <div className="font-mono text-muted uppercase text-sm">Loading calendar snapshot...</div>
      ) : calendar.state === 'available' && calendar.data ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {calendar.data.map((ev: CalendarEntry) => (
            <Panel key={ev.sourceTournamentId}>
              <div className="flex justify-between items-start mb-2">
                <h4 className="font-display uppercase text-lg text-paper">{ev.name}</h4>
                <ContractChip state={ev.eligibilityStatus === 'ELIGIBLE' ? 'available' : 'withheld'} label={ev.eligibilityStatus} />
              </div>
              <p className="font-body text-xs text-muted mb-1">{ev.category}</p>
              <div className="font-mono text-[10px] text-muted space-y-1 mt-3 pt-3 border-t border-line/50">
                <p>Venue: {ev.countryCity || 'Unavailable'}</p>
                <p>Dates: {ev.startDate} to {ev.endDate}</p>
                <p>Snapshot Status: {ev.immutableProvenance?.snapshotStatus || 'Unknown'}</p>
              </div>
              <button className="mt-4 w-full py-2 bg-ink border border-line text-xs font-mono uppercase text-acid hover:bg-panel-strong">Inspect</button>
            </Panel>
          ))}
        </div>
      ) : (
        <ProviderError state={calendar.state} reason="No verified calendar records retrieved. Contract unavailable." />
      )}
    </div>
  );
}
