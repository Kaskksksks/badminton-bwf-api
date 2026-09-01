import React, { useEffect, useState } from 'react';
import { SectionHeader, ProviderError, Panel, ContractChip, EmptyState } from '../components';
import { fetchMatches } from '../api';
import type { MatchRecord, CapabilityState } from '../types/badminton';

export function MatchCentre() {
  const [matches, setMatches] = useState<{data: MatchRecord[] | null, state: CapabilityState, reason?: string}>({ data: null, state: 'loading' });
  const [search, setSearch] = useState('');
  
  useEffect(() => {
    fetchMatches().then(res => setMatches(res));
  }, []);

  const filtered = matches.data?.filter(m => 
    m.participant1.name.toLowerCase().includes(search.toLowerCase()) || 
    m.participant2.name.toLowerCase().includes(search.toLowerCase()) ||
    m.tournament.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="Match intelligence" 
        title="Searchable senior match slate" 
        chip="Live support"
        description="Search or filter only the eligible, server-normalized match records returned by the provider. Completed matches show official scores in preference to any forecast surface." 
      />
      
      <div className="flex gap-4 mb-6">
        <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search player, pair, country, tournament, court, round…" className="w-full bg-ink border border-line p-3 font-mono text-sm text-paper placeholder-muted focus:outline-none focus:border-acid" />
      </div>

      {matches.state === 'loading' ? (
         <div className="font-mono text-muted uppercase text-sm">Loading matches...</div>
      ) : matches.state === 'available' && filtered ? (
         <div className="space-y-4">
           {filtered.length > 0 ? filtered.map(m => (
             <Panel key={m.id} className="hover:bg-panel-strong transition-colors cursor-pointer border border-line">
               <div className="flex justify-between items-start mb-4">
                 <div>
                   <h4 className="font-mono text-xs uppercase text-acid mb-1">{m.tournament.name} • {m.round}</h4>
                   <p className="font-mono text-[10px] text-muted">{m.datesAndTimes} • {m.court} • {m.discipline}</p>
                 </div>
                 <ContractChip state="available" label={m.normalizedStatus} />
               </div>
               
               <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 py-4 border-y border-line/30">
                 <div className="text-right">
                   <p className={`font-display text-lg uppercase ${m.winnerId === m.participant1.id ? 'text-paper' : 'text-muted'}`}>{m.participant1.name}</p>
                   <p className="font-mono text-[10px] text-muted">{m.participant1.countryCode}</p>
                 </div>
                 <div className="text-center">
                   <div className="font-mono text-xl text-acid px-4 py-1 bg-ink border border-line tracking-widest">{m.rawScore || 'vs'}</div>
                 </div>
                 <div className="text-left">
                   <p className={`font-display text-lg uppercase ${m.winnerId === m.participant2.id ? 'text-paper' : 'text-muted'}`}>{m.participant2.name}</p>
                   <p className="font-mono text-[10px] text-muted">{m.participant2.countryCode}</p>
                 </div>
               </div>
               <div className="mt-4 flex justify-between items-center font-mono text-[10px] text-muted uppercase">
                 <span>Confidence: {m.scoreSourceConfidence}</span>
                 <span>View full breakdown →</span>
               </div>
             </Panel>
           )) : (
             <EmptyState message="No matching matches found." />
           )}
         </div>
      ) : (
         <ProviderError state={matches.state} reason={matches.reason || "Unable to fetch match slate"} />
      )}
    </div>
  );
}
