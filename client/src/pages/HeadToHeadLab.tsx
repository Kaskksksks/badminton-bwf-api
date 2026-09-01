import React, { useEffect, useState } from 'react';
import { SectionHeader, Panel, ContractChip, EmptyState } from '../components';
import { fetchActiveParticipants, fetchHeadToHead } from '../api';
import type { ActiveParticipant, CapabilityState } from '../types/badminton';

export function HeadToHeadLab() {
  const [participants, setParticipants] = useState<{data: ActiveParticipant[] | null, state: CapabilityState, reason?: string}>({ data: null, state: 'loading', reason: 'Loading' });
  const [p1, setP1] = useState<string>('');
  const [p2, setP2] = useState<string>('');
  const [h2h, setH2h] = useState<any>({ data: null, state: 'loading', reason: 'Loading' });

  useEffect(() => {
    fetchActiveParticipants().then(res => {
      setParticipants(res);
      if (res.data && res.data.length > 1) {
        setP1(res.data[0].id);
        setP2(res.data[1].id);
      }
    });
  }, []);

  useEffect(() => {
    if (p1 && p2 && p1 !== p2) {
      setH2h({ data: null, state: 'loading', reason: 'Loading' });
      fetchHeadToHead(p1, p2, 'MS').then(res => setH2h(res));
    }
  }, [p1, p2]);

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="Identity-safe comparison" 
        title="Head-to-Head lab" 
        description="Choose only current, confirmed active singles competitors or pairs. The selection pool is senior-safe by contract; no local name matching or pair construction occurs in the browser." 
      />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Panel>
          <span className="font-mono text-xs uppercase text-muted mb-2 block">Competitor A</span>
          <select className="w-full bg-ink border border-line p-2 font-mono text-sm text-paper" value={p1} onChange={(e) => setP1(e.target.value)}>
             {participants.state === 'loading' && <option>Loading...</option>}
             {participants.state !== 'loading' && (!participants.data || participants.data.length === 0) && <option>Active participant contract unavailable</option>}
             {participants.data?.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Panel>
        <Panel>
          <span className="font-mono text-xs uppercase text-muted mb-2 block">Competitor B</span>
          <select className="w-full bg-ink border border-line p-2 font-mono text-sm text-paper" value={p2} onChange={(e) => setP2(e.target.value)}>
             {participants.state === 'loading' && <option>Loading...</option>}
             {participants.state !== 'loading' && (!participants.data || participants.data.length === 0) && <option>Active participant contract unavailable</option>}
             {participants.data?.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Panel>
      </div>
      
      {p1 === p2 ? (
         <Panel className="flex items-center justify-center p-12">
           <EmptyState message="Please select two different competitors." />
         </Panel>
      ) : h2h.state === 'loading' ? (
         <div className="font-mono text-muted uppercase text-sm mt-8">Analyzing historical records...</div>
      ) : h2h.state === 'available' && h2h.data ? (
         <div className="space-y-6 mt-8">
           <div className="flex justify-between items-center px-4 py-8 bg-ink border border-line">
             <div className="text-center w-1/3">
               <span className="block font-display text-4xl text-paper">{h2h.data.participant1Wins}</span>
               <span className="font-mono text-[10px] text-muted uppercase tracking-widest mt-2 block">Wins</span>
             </div>
             <div className="text-center w-1/3 border-x border-line/30 px-4">
               <span className="block font-mono text-[10px] text-acid uppercase mb-2">Total Encounters</span>
               <span className="block font-display text-2xl text-paper">{h2h.data.totalMatches}</span>
             </div>
             <div className="text-center w-1/3">
               <span className="block font-display text-4xl text-paper">{h2h.data.participant2Wins}</span>
               <span className="font-mono text-[10px] text-muted uppercase tracking-widest mt-2 block">Wins</span>
             </div>
           </div>

           <h4 className="font-mono text-xs uppercase text-acid mt-8 mb-4">Latest Encounter</h4>
           {h2h.data.lastEncounter && (
             <Panel className="border border-line">
               <div className="flex justify-between items-start mb-4">
                 <div>
                   <h4 className="font-mono text-xs uppercase text-paper mb-1">{h2h.data.lastEncounter.tournament.name} • {h2h.data.lastEncounter.round}</h4>
                   <p className="font-mono text-[10px] text-muted">{h2h.data.lastEncounter.datesAndTimes} • {h2h.data.lastEncounter.court} • {h2h.data.lastEncounter.discipline}</p>
                 </div>
                 <ContractChip state="available" label="completed" />
               </div>
               
               <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 py-4 border-y border-line/30">
                 <div className="text-right">
                   <p className="font-display text-lg uppercase text-paper">{h2h.data.lastEncounter.participant1.name}</p>
                   <p className="font-mono text-[10px] text-muted">{h2h.data.lastEncounter.participant1.countryCode}</p>
                 </div>
                 <div className="text-center">
                   <div className="font-mono text-xl text-acid px-4 py-1 bg-ink border border-line tracking-widest">{h2h.data.lastEncounter.rawScore}</div>
                 </div>
                 <div className="text-left">
                   <p className="font-display text-lg uppercase text-muted">{h2h.data.lastEncounter.participant2.name}</p>
                   <p className="font-mono text-[10px] text-muted">{h2h.data.lastEncounter.participant2.countryCode}</p>
                 </div>
               </div>
             </Panel>
           )}
         </div>
      ) : (
         <Panel className="flex items-center justify-center p-12">
           <EmptyState message="Comparison unavailable or insufficient historical data." />
         </Panel>
      )}
            
      <p className="font-mono text-[10px] text-muted max-w-2xl border-t border-line pt-4 mt-8">
        Head-to-head is an evidence contributor, not a conclusion. No probability or margin may be displayed unless a separate validated model snapshot exists.
      </p>
    </div>
  );
}
