import React, { useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import html2canvas from 'html2canvas';
import {
  ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceArea, ReferenceLine
} from 'recharts';

// Helper for BF scale
function bfScale(windSpeedMs) {
  const ws = parseFloat(windSpeedMs);
  if (isNaN(ws)) return 0;
  if (ws < 0.3) return 0;
  if (ws < 1.6) return 1;
  if (ws < 3.4) return 2;
  if (ws < 5.5) return 3;
  if (ws < 8.0) return 4;
  if (ws < 10.8) return 5;
  if (ws < 13.9) return 6;
  if (ws < 17.2) return 7;
  if (ws < 20.8) return 8;
  if (ws < 24.5) return 9;
  if (ws < 28.5) return 10;
  if (ws < 32.7) return 11;
  return 12;
}

// Matches backend cp_calculator.py's _is_fair_weather() and
// voyagePdfExport.js's isFairWeatherRow() exactly — reads BF_Wind directly
// (not recomputed from True_Wind_Spd_ms) with the real 3.0m wave threshold.
// This file had its own separate, stale copy of the old broken pattern
// (bfScale-recompute + a hardcoded 1.25m instead of 3.0m) that drove both
// the Ship Speed chart's good/adverse shading and the Wave Height chart's
// "CP Wave" reference line — found 2026-09 via a manager-reviewed report
// showing the reference line and shading disagreeing with the report's own
// stated "Sig.Wave 3.0m" Good Weather Definition.
const FAIR_BF_MAX = 4.0
const FAIR_WAVE_MAX_M = 3.0
function isFairWeatherRow(r) {
  const bf = r.BF_Wind != null && r.BF_Wind !== '' ? +r.BF_Wind : null
  const hs = r.Sig_Wave_Ht_m != null && r.Sig_Wave_Ht_m !== '' ? +r.Sig_Wave_Ht_m : null
  if (bf == null && hs == null) return true
  if (bf == null || hs == null) return false
  return bf <= FAIR_BF_MAX && hs <= FAIR_WAVE_MAX_M
}

export function capturePdfAssets(sum, seriesRows, cpData) {
  return new Promise((resolve) => {
    const div = document.createElement('div');
    div.style.position = 'absolute';
    div.style.top = '-9999px';
    div.style.left = '-9999px';
    document.body.appendChild(div);

    const root = createRoot(div);

    const handleComplete = (assets) => {
      // Small timeout to let DOM clean up
      setTimeout(() => {
        root.unmount();
        div.remove();
        resolve(assets);
      }, 100);
    };

    root.render(
      <PdfAssetsRenderer sum={sum} seriesRows={seriesRows} cpData={cpData} onComplete={handleComplete} />
    );
  });
}

function PdfAssetsRenderer({ sum, seriesRows, cpData, onComplete }) {
  const chartsRef = useRef(null);

  const cpW = cpData?.warranty || {};
  const foW = +(cpW.fo_mt_day || 0);
  const goW = +(cpW.go_mt_day || 0);
  const speedW = +(cpW.speed_kn || 0);

  useEffect(() => {
    // Wait for recharts animations
    const timer = setTimeout(async () => {
      try {
        const chartsCanvas = await html2canvas(chartsRef.current, { scale: 2, useCORS: true, logging: false });
        
        onComplete({
          chartsDataUrl: chartsCanvas.toDataURL('image/jpeg', 0.95),
          mapDataUrl: null
        });
      } catch (err) {
        console.error("Failed to capture PDF assets", err);
        onComplete({ chartsDataUrl: null, mapDataUrl: null });
      }
    }, 1500); // 1.5s to ensure charts render (no map tiles to wait for)
    return () => clearTimeout(timer);
  }, [onComplete]);

  const data = seriesRows.map((r, idx) => {
    const wh = +(r.Sig_Wave_Ht_m) || 0;
    const isGood = isFairWeatherRow(r);

    return {
      index: idx,
      name: r.Date && typeof r.Date === 'string' && r.Date.length >= 10 ? `${r.Date.substring(8, 10)}/${r.Date.substring(5, 7)}` : '',
      sog: +(r.SOG_kn || 0),
      fo: +(r.ME_FOC_MT || 0),
      dogo: +(r.AE_FOC_MT || 0) + +(r.Boiler_FOC_MT || 0),
      rpm: +(r.Shaft_RPM || 0),
      wind: r.BF_Wind != null ? +r.BF_Wind : (+bfScale(r.True_Wind_Spd_ms) || 0),
      wave: wh,
      current: +(r.Current_Spd_kn || 0),
      isGood,
      cpSpeed: speedW,
      cpFo: foW,
      cpDogo: goW
    };
  });

  return (
    <div style={{ width: '1000px', background: 'white', color: '#000' }}>
      
      {/* CHARTS CONTAINER */}
      <div ref={chartsRef} style={{ width: '1000px', height: '1400px', padding: '20px', background: 'white', color: '#000' }}>
        <h2 style={{ textAlign: 'center', fontFamily: 'sans-serif', marginBottom: '20px', color: '#000', fontWeight: 'bold' }}>Speed and Consumption with Weather / Current Analysis</h2>
        
        {/* SHIP SPEED */}
        <h4 style={{ fontFamily: 'sans-serif', margin: '5px 0', color: '#000', fontWeight: 'bold' }}>[ Ship Speed and RPM ]</h4>
        <div style={{ height: '220px', width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="left" domain={['auto', 'auto']} tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="right" orientation="right" tick={{fontSize: 12, fill: '#000'}} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: '12px', color: '#000' }} />
              {data.map((entry, index) => (
                <ReferenceArea key={index} yAxisId="left" x1={data[index]?.name} x2={data[index+1]?.name || data[index]?.name} fill={entry.isGood ? '#fff2cc' : '#f0f0f0'} fillOpacity={1} />
              ))}
              <ReferenceLine yAxisId="left" y={speedW} stroke="red" label={{ value: 'CP Speed', fontSize: 12, fill: '#000', position: 'right' }} />
              <Line yAxisId="left" type="monotone" dataKey="sog" name="Daily Average Speed" stroke="blue" dot={{fill:'blue'}} isAnimationActive={false} />
              <Line yAxisId="right" type="monotone" dataKey="rpm" name="RPM" stroke="#009933" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {/* FO CONSUMPTION */}
        <h4 style={{ fontFamily: 'sans-serif', margin: '15px 0 5px 0', color: '#000', fontWeight: 'bold' }}>[ FO Consumption and RPM ]</h4>
        <div style={{ height: '220px', width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="left" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="right" orientation="right" tick={{fontSize: 12, fill: '#000'}} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: '12px', color: '#000' }} />
              <ReferenceLine yAxisId="left" y={foW} stroke="red" label={{ value: 'CP FO', fontSize: 12, fill: '#000', position: 'insideTopRight' }} />
              <Bar yAxisId="left" dataKey="fo" name="Ship Reported Daily FO" fill="#ffcc66" isAnimationActive={false} />
              <Line yAxisId="right" type="monotone" dataKey="rpm" name="RPM" stroke="blue" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {/* DO/GO CONSUMPTION */}
        <h4 style={{ fontFamily: 'sans-serif', margin: '15px 0 5px 0', color: '#000', fontWeight: 'bold' }}>[ DO/GO Consumption and RPM ]</h4>
        <div style={{ height: '220px', width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="left" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="right" orientation="right" tick={{fontSize: 12, fill: '#000'}} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: '12px', color: '#000' }} />
              <ReferenceLine yAxisId="left" y={goW} stroke="red" />
              <Bar yAxisId="left" dataKey="dogo" name="Ship Reported Daily DO/GO" fill="#ffcc66" isAnimationActive={false} />
              <Line yAxisId="right" type="monotone" dataKey="rpm" name="RPM" stroke="blue" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {/* WIND SPEED */}
        <h4 style={{ fontFamily: 'sans-serif', margin: '15px 0 5px 0', color: '#000', fontWeight: 'bold' }}>[ Wind Speed ]</h4>
        <div style={{ height: '220px', width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis tick={{fontSize: 12, fill: '#000'}} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: '12px', color: '#000' }} />
              <ReferenceLine y={4.0} stroke="red" label={{ value: 'Good Weather Max', fontSize: 11, fill: '#000', position: 'insideTopRight' }} />
              <Line type="monotone" dataKey="wind" name="Wind Beaufort Force (BF)" stroke="green" dot={{fill:'green'}} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {/* WAVE HEIGHT & CURRENT */}
        <h4 style={{ fontFamily: 'sans-serif', margin: '15px 0 5px 0', color: '#000', fontWeight: 'bold' }}>[ Wave Height / Current Factor ]</h4>
        <div style={{ height: '220px', width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="left" tick={{fontSize: 12, fill: '#000'}} />
              <YAxis yAxisId="right" orientation="right" tick={{fontSize: 12, fill: '#000'}} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: '12px', color: '#000' }} />
              <ReferenceLine yAxisId="left" y={FAIR_WAVE_MAX_M} stroke="red" label={{ value: 'CP Wave', fontSize: 12, fill: '#000', position: 'insideTopRight' }} />
              <ReferenceLine yAxisId="right" y={0} stroke="red" />
              <Line yAxisId="left" type="monotone" dataKey="wave" name="Wave Height (m)" stroke="green" dot={{fill:'blue', shape:'square'}} isAnimationActive={false} />
              <Line yAxisId="right" type="monotone" dataKey="current" name="Current Factor" stroke="blue" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

    </div>
  );
}
