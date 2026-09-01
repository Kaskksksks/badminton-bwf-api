import React, { useEffect, useState } from "react";
import { SectionHeader, EmptyState, Panel, ProviderError } from '../components';
import { fetchRankings } from '../api';

export function Rankings() {
  const [rankings, setRankings] = useState<any>({ data: null, state: 'loading', reason: 'Loading' });

  useEffect(() => {
    fetchRankings().then(res => setRankings(res));
  }, []);

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="Rankings intelligence" 
        chip="Official senior provider ranking"
        title="Official ranking when the snapshot is complete." 
        description="Only a complete senior provider snapshot with discipline, effective date, provenance, and confirmed subject identity is rendered. Internal ratings and comparative claims are not inferred from a missing snapshot." 
      />
      
      <div className="flex gap-2">
         {['ALL (MS)', 'WS', 'MD', 'WD', 'XD'].map(d => (
           <button key={d} className={`px-3 py-1 border border-line font-mono text-xs uppercase ${d === 'ALL (MS)' ? 'bg-acid text-ink' : 'bg-ink text-muted hover:text-paper'}`}>{d}</button>
         ))}
      </div>

      {rankings.state === 'loading' ? (
        <div className="font-mono text-muted uppercase text-sm">Loading rankings...</div>
      ) : rankings.state === 'available' && rankings.data ? (
        <Panel className="border border-line">
          <div className="mb-4 flex justify-between">
            <h3 className="font-mono text-sm text-acid uppercase">BWF World Rankings • {rankings.data.discipline}</h3>
            <span className="font-mono text-[10px] text-muted">Snapshot: {rankings.data.publicationDate}</span>
          </div>
          <table className="w-full text-left font-mono text-sm">
            <thead>
              <tr className="border-b border-line/30 text-muted uppercase text-[10px]">
                <th className="py-2">Rank</th>
                <th className="py-2">Player</th>
                <th className="py-2">Country</th>
                <th className="py-2 text-right">Points</th>
                <th className="py-2 text-right">Tourneys</th>
              </tr>
            </thead>
            <tbody>
              {rankings.data.entries.map((entry: any) => (
                <tr key={entry.rank} className="border-b border-line/10 hover:bg-panel-strong transition-colors">
                  <td className="py-3 text-acid w-16">
                    {entry.rank} 
                    {entry.movement > 0 && <span className="text-green-500 ml-2">↑{entry.movement}</span>}
                    {entry.movement < 0 && <span className="text-red-500 ml-2">↓{Math.abs(entry.movement)}</span>}
                    {entry.movement === 0 && <span className="text-muted ml-2">-</span>}
                  </td>
                  <td className="py-3 font-display uppercase tracking-wide text-paper">{entry.participant.name}</td>
                  <td className="py-3 text-muted">{entry.participant.countryCode}</td>
                  <td className="py-3 text-right text-paper">{entry.points.toLocaleString()}</td>
                  <td className="py-3 text-right text-muted">{entry.tournaments}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      ) : (
        <ProviderError state={rankings.state} reason={rankings.reason || "Ranking snapshot withheld"} />
      )}
    </div>
  );
}
