import React, { useEffect, useState } from "react";
import { SectionHeader, EmptyState, Panel, ProviderError } from '../components';
import { fetchAccuracy } from '../api';

export function Accuracy() {
  const [accuracy, setAccuracy] = useState<any>({ data: null, state: 'loading', reason: 'Loading' });

  useEffect(() => {
    fetchAccuracy().then(res => setAccuracy(res));
  }, []);

  return (
    <div className="space-y-6">
      <SectionHeader 
        eyebrow="Evaluation ledger" 
        chip="System metrics"
        title="Predictive performance tracking" 
        description="Transparent tracking of model accuracy against official provider match outcomes. Automatically reconciled when source scores are validated." 
      />

      {accuracy.state === 'loading' ? (
        <div className="font-mono text-muted uppercase text-sm">Loading accuracy ledger...</div>
      ) : accuracy.state === 'available' && accuracy.data ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Panel className="border border-line">
            <h3 className="font-mono text-sm text-acid uppercase mb-4">Overall Performance ({accuracy.data.period})</h3>
            <div className="grid grid-cols-2 gap-6 mb-6">
              <div>
                <p className="font-mono text-[10px] text-muted uppercase mb-1">Win Prediction Accuracy</p>
                <p className="font-display text-4xl text-paper">{accuracy.data.metrics.overallAccuracy}%</p>
              </div>
              <div>
                <p className="font-mono text-[10px] text-muted uppercase mb-1">Total Verified Matches</p>
                <p className="font-display text-4xl text-paper">{accuracy.data.metrics.totalPredictions}</p>
              </div>
              <div>
                <p className="font-mono text-[10px] text-muted uppercase mb-1">Calibration Score</p>
                <p className="font-mono text-xl text-paper">{accuracy.data.metrics.calibrationScore}</p>
              </div>
              <div>
                <p className="font-mono text-[10px] text-muted uppercase mb-1">Brier Score (Lower is better)</p>
                <p className="font-mono text-xl text-paper">{accuracy.data.metrics.brierScore}</p>
              </div>
            </div>
          </Panel>

          <Panel className="border border-line">
            <h3 className="font-mono text-sm text-acid uppercase mb-4">Accuracy By Discipline</h3>
            <div className="space-y-4">
              {Object.entries(accuracy.data.byDiscipline).map(([disc, val]) => (
                <div key={disc}>
                  <div className="flex justify-between font-mono text-xs text-muted mb-1 uppercase">
                    <span>{disc}</span>
                    <span className="text-paper">{String(val)}%</span>
                  </div>
                  <div className="w-full bg-ink h-2 border border-line">
                    <div className="bg-acid h-full" style={{ width: `${val}%` }}></div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      ) : (
        <ProviderError state={accuracy.state} reason={accuracy.reason || "Evaluation unavailable"} />
      )}
    </div>
  );
}
