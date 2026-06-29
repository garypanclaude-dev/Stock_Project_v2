// 主圖（K 棒）與成交量副圖。
//
// 每個函式接受 ctx + 資料 + 設定 → 回傳新建立的 Chart instance。
// 不負責 destroy 既有 instance —— 由呼叫端（StockView）持有引用並在重繪/卸載時釋放。

import { CandlestickPlugin, PatternMarkerPlugin, thinLabels } from './chart-plugins.js';
import { fmtVol } from '../../services/formatters.js';

const MA_COLORS = { ma5: '#f59e0b', ma10: '#3b82f6', ma20: '#a855f7', ma60: '#ec4899' };
const BB_COLOR = '#06b6d4';

export function renderCandlestick(canvas, klines, indicators, patterns, activeOverlays) {
  const ctx = canvas.getContext('2d');
  const lo = Math.min(...klines.map(k => k.low));
  const hi = Math.max(...klines.map(k => k.high));
  const pad = (hi - lo) * 0.12;
  const datasets = [{ data: klines.map(k => [k.low, k.high]), backgroundColor: 'transparent', borderColor: 'transparent' }];

  if (indicators?.ma) {
    for (const [key, color] of Object.entries(MA_COLORS)) {
      if (activeOverlays.has(key) && indicators.ma[key]) {
        datasets.push({ type:'line', label:key.toUpperCase(), data:indicators.ma[key], borderColor:color, borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true });
      }
    }
  }
  if (activeOverlays.has('bb') && indicators?.bollinger) {
    datasets.push({ type:'line', label:'BB Upper', data:indicators.bollinger.upper, borderColor:BB_COLOR, borderWidth:1, borderDash:[4,3], pointRadius:0, tension:0.3, spanGaps:true, fill:false });
    datasets.push({ type:'line', label:'BB Lower', data:indicators.bollinger.lower, borderColor:BB_COLOR, borderWidth:1, borderDash:[4,3], pointRadius:0, tension:0.3, spanGaps:true, fill:'-1', backgroundColor:'rgba(6,182,212,.06)' });
  }

  const chart = new Chart(ctx, {
    type:'bar', data:{ labels: thinLabels(klines), datasets },
    options:{
      responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{
        x:{grid:{color:'#1e293b'}, ticks:{color:'#64748b',font:{size:10},maxRotation:0}, border:{color:'#334155'}},
        y:{position:'right', min:lo-pad, max:hi+pad, grid:{color:'#1e293b80'}, ticks:{color:'#64748b',font:{size:11}, callback:v=>'$'+v.toFixed(1)}, border:{color:'#334155'}},
      },
      plugins:{legend:{display:false}, tooltip:{callbacks:{title:items=>klines[items[0].dataIndex]?.date||'', label:item=>{if(item.datasetIndex===0){const k=klines[item.dataIndex];return[`  Open  $${k.open.toFixed(2)}`,`  High  $${k.high.toFixed(2)}`,`  Low   $${k.low.toFixed(2)}`,`  Close $${k.close.toFixed(2)}`]}return`  ${item.dataset.label}: $${item.raw?.toFixed(2)??'–'}`}}, backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, titleColor:'#f1f5f9', bodyColor:'#94a3b8', padding:10}},
    },
    plugins:[CandlestickPlugin, PatternMarkerPlugin],
  });
  chart._klines = klines;
  chart._patterns = patterns || [];
  return chart;
}

export function renderVolume(canvas, klines) {
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type:'bar',
    data:{ labels: klines.map(()=>''),
      datasets:[{ data: klines.map(k=>k.volume),
        backgroundColor: klines.map(k=>k.close>=k.open?'rgba(34,197,94,.45)':'rgba(239,68,68,.45)'),
        borderWidth:0 }]},
    options:{ responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{ x:{display:false}, y:{display:true, position:'right', ticks:{color:'#475569',font:{size:9},callback:v=>fmtVol(v)}, grid:{display:false}, border:{display:false}}},
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:item=>`  Volume  ${fmtVol(item.raw)}`}, backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, bodyColor:'#94a3b8', padding:10}}},
  });
}
