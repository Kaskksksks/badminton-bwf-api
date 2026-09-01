import React, { useEffect, useState } from 'react';
import { SectionHeader, EmptyState, Panel, ContractChip } from '../components';
import { fetchActiveParticipants } from '../api';
import type { ActiveParticipant, CapabilityState } from '../types/badminton';

export function PlayerIntel() {
  const [participants, setParticipants] = useState<{data: ActiveParticipant[] | null, state: CapabilityState}>({ data: null, state: 'loading' });
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    fetchActiveParticipants().then(res => setParticipants(res));
  }, []);

  const filtered = participants.data?.filter(p => p.name?.toLowerCase().includes(searchTerm.toLowerCase()));

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="Player intelligence" 
        chip="Senior eligibility required"
        title="Profiles with provenance." 
        description="The directory contains only confirmed identities with current approved senior activity. Singles and confirmed pairs remain separate analytical subjects." 
      />
      <input 
        type="text" 
        placeholder="Find an active player or pair…" 
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        className="w-full bg-ink border border-line p-3 font-mono text-sm text-paper placeholder-muted focus:outline-none focus:border-acid" 
      />
      
      {participants.state === 'loading' ? (
        <div className="font-mono text-muted uppercase text-sm">Loading participants...</div>
      ) : participants.state === 'available' && filtered ? (
        filtered.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map(p => (
              <Panel key={p.id}>
                <div className="flex justify-between items-start mb-2">
                  <h4 className="font-display uppercase text-lg text-paper">{p.name}</h4>
                  <ContractChip state="available" label={p.identityStatus || 'CONFIRMED'} />
                </div>
                <div className="font-mono text-[10px] text-muted space-y-1 mb-4">
                  <p>Type: <span className="text-paper uppercase">{p.kind || 'Unknown'}</span></p>
                  <p>Recent Eligible Matches: <span className="text-paper">{p.recentEligibleMatchCount || 0}</span></p>
                  <p>Latest Match: <span className="text-paper">{p.latestEligibleMatchDate || 'N/A'}</span></p>
                </div>
                <button className="w-full py-2 bg-ink border border-line text-xs font-mono uppercase text-acid hover:bg-panel-strong">Open profile</button>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState message="No matching participants found." />
        )
      ) : (
        <EmptyState message="Active participant contract unavailable" />
      )}
      
      <p className="font-mono text-[10px] text-muted border-t border-line pt-4">Form, rating, and predictive claims remain withheld unless a separately evaluated model contract supplies those fields.</p>
    </div>
  );
}
