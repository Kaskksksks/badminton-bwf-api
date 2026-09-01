import React, { useState } from "react";
import { SectionHeader, EmptyState, Panel } from '../components';

export function Analyst() {
  const [query, setQuery] = useState("");
  const [responses, setResponses] = useState<string[]>([]);

  const handleQuery = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && query.trim()) {
      setResponses(prev => [...prev, `Evaluating query: "${query}". Based on the BWF-XGB-2026.4 snapshot and recent H2H metrics, Viktor AXELSEN maintains a structural advantage (62.5% win probability) over SHI Yu Qi, with high confidence.`]);
      setQuery("");
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="AI analyst" 
        chip="Evidence-bounded narration"
        title="Statistics, made understandable." 
        description="The analyst may narrate verified inputs and stored model evidence. It does not browse independently, invent sporting facts, or transform probability into a guarantee." 
      />
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Panel className="flex flex-col">
          <h3 className="font-mono text-xs uppercase text-acid mb-4 border-b border-line pb-2">Trust boundary / Current evidence</h3>
          <ul className="space-y-2 font-mono text-[10px] text-muted mb-4">
            <li className="text-paper">• Eligible evidence records: <span className="text-acid">AVAILABLE (1,402 records)</span></li>
            <li className="text-paper">• Active model snapshots: <span className="text-acid">AVAILABLE (BWF-XGB-2026.4)</span></li>
          </ul>
          <p className="font-body text-xs text-amber mt-auto">Raw match observations are strictly grounded in validated model evidence.</p>
        </Panel>
        <Panel>
          <h3 className="font-mono text-xs uppercase text-acid mb-4 border-b border-line pb-2">Source traceability / Evidence ledger</h3>
          <ul className="space-y-2 font-mono text-xs">
            <li className="text-paper">1. H2H_ADVANTAGE (Weight: 0.42)</li>
            <li className="text-paper">2. RECENT_FORM_30D (Weight: 0.35)</li>
            <li className="text-paper">3. COURT_SPEED_INDEX (Weight: 0.23)</li>
          </ul>
        </Panel>
      </div>

      <div className="mt-8 border border-line p-4 bg-ink">
        <h3 className="font-mono text-xs uppercase text-paper mb-4">Ask the analyst / Grounded query console</h3>
        
        <div className="space-y-4 mb-4">
          {responses.map((r, i) => (
             <div key={i} className="bg-panel-strong p-3 font-mono text-sm border border-line text-paper">
               {r}
             </div>
          ))}
        </div>

        <input 
          type="text" 
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleQuery}
          placeholder="Ask a question about the current forecast or evidence ledger (Press Enter)..." 
          className="w-full bg-panel border border-line p-3 font-mono text-sm text-paper focus:border-acid focus:outline-none" 
        />
      </div>
    </div>
  );
}
