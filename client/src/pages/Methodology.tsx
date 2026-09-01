import React from "react";

import { SectionHeader, Panel } from '../components';

export function Methodology() {
  return (
    <div className="space-y-6">
      <SectionHeader eyebrow="Methodology" chip="Explainability protocol" title="A forecast must earn the right to exist." description="The platform treats data provenance, validation, timing, and uncertainty as primary information. A compelling interface does not make an unsupported sporting claim reliable." />
      
      <div className="space-y-4">
        {[
          { step: '01', title: 'Ingestion', desc: 'The server retrieves provider data; credentials stay private.' },
          { step: '02', title: 'Validation', desc: 'Identity, score, status, source, and freshness fields are checked.' },
          { step: '03', title: 'Evidence', desc: 'Eligible historical and context inputs are stored with cutoffs.' },
          { step: '04', title: 'Model', desc: 'A versioned, activated model snapshot is required before a forecast.' },
          { step: '05', title: 'Narration', desc: 'The analyst cites contributing metrics and uncertainty, never certainty.' }
        ].map(s => (
          <Panel key={s.step} className="flex gap-4">
            <div className="font-mono text-acid text-xl">{s.step}</div>
            <div>
              <h4 className="font-mono text-sm uppercase text-paper mb-1">{s.title}</h4>
              <p className="font-body text-sm text-muted">{s.desc}</p>
            </div>
          </Panel>
        ))}
      </div>

      <Panel className="bg-panel-strong mt-8 border-line-bright/30">
        <h3 className="font-mono text-xs uppercase text-acid mb-2">Settlement Rule</h3>
        <p className="font-body text-sm text-paper leading-relaxed">
          When an official completed outcome enters the provider feed, it replaces a forecast as the display result. The platform preserves the prediction snapshot only for accuracy evaluation when the model contract supports it. Remaining tournament forecasts may be recomputed only from validated results and an activated model; otherwise the forecast surface remains withheld.
        </p>
      </Panel>
    </div>
  );
}
