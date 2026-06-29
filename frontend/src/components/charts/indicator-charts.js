// 技術指標副圖：RSI / MACD / KD / OBV。
// 每個函式回傳新 Chart instance；呼叫端負責 destroy。

import { thinLabels } from './chart-plugins.js';
import { fmtVol } from '../../services/formatters.js';

export function renderRSI(canvas, klines, indicators) {
  if (!indicators?.rsi) return null;
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type:'line',
    data:{ labels: thinLabels(klines), datasets:[{ data: indicators.rsi, borderColor:'#a855f7', borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true, fill:false }]},
    options:{ responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{ x:{grid:{color:'#1e293b'}, ticks:{color:'#64748b',font:{size:9},maxRotation:0}, border:{color:'#334155'}},
        y:{position:'right', min:0, max:100, grid:{color:c2=>[30,70].includes(c2.tick.value)?'#475569':'#1e293b40'}, ticks:{color:'#64748b',font:{size:10},stepSize:10}, border:{color:'#334155'}}},
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:item=>`  RSI: ${item.raw?.toFixed(1)??'–'}`}, backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, bodyColor:'#94a3b8', padding:8}}},
    plugins:[{
      id:'rsi-zones',
      beforeDatasetsDraw(chart){
        const{ctx:c, chartArea:{left,right}, scales:{y}}=chart;
        c.save();
        c.fillStyle='rgba(239,68,68,.06)';
        c.fillRect(left, y.getPixelForValue(100), right-left, y.getPixelForValue(70)-y.getPixelForValue(100));
        c.fillStyle='rgba(34,197,94,.06)';
        c.fillRect(left, y.getPixelForValue(30), right-left, y.getPixelForValue(0)-y.getPixelForValue(30));
        c.restore();
      }
    }],
  });
}

export function renderMACD(canvas, klines, indicators) {
  if (!indicators?.macd) return null;
  const ctx = canvas.getContext('2d');
  const hist = indicators.macd.histogram || [];
  return new Chart(ctx, {
    type:'bar',
    data:{ labels: thinLabels(klines), datasets:[
      { data: hist.map(v=>v??0),
        backgroundColor: hist.map(v=>v===null?'transparent':v>=0?'rgba(34,197,94,.6)':'rgba(239,68,68,.6)'), borderWidth:0, order:2 },
      { type:'line', label:'MACD', data: indicators.macd.macd, borderColor:'#3b82f6', borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true, order:1 },
      { type:'line', label:'Signal', data: indicators.macd.signal, borderColor:'#f59e0b', borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true, order:1 },
    ]},
    options:{ responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{ x:{grid:{color:'#1e293b'}, ticks:{color:'#64748b',font:{size:9},maxRotation:0}, border:{color:'#334155'}},
        y:{position:'right', grid:{color:'#1e293b80'}, ticks:{color:'#64748b',font:{size:10}}, border:{color:'#334155'}}},
      plugins:{ legend:{display:true, position:'top', align:'end', labels:{color:'#94a3b8', boxWidth:10, boxHeight:10, font:{size:10}, usePointStyle:true, padding:12, filter:item=>item.datasetIndex>0}},
        tooltip:{backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, bodyColor:'#94a3b8', padding:8}}},
  });
}

export function renderKD(canvas, klines, indicators) {
  if (!indicators?.kd) return null;
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type:'line',
    data:{ labels: thinLabels(klines), datasets:[
      { label:'K', data: indicators.kd.k, borderColor:'#3b82f6', borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true },
      { label:'D', data: indicators.kd.d, borderColor:'#f59e0b', borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true },
    ]},
    options:{ responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{ x:{grid:{color:'#1e293b'}, ticks:{color:'#64748b',font:{size:9},maxRotation:0}, border:{color:'#334155'}},
        y:{position:'right', min:0, max:100, grid:{color:c=>[20,80].includes(c.tick.value)?'#475569':'#1e293b40'}, ticks:{color:'#64748b',font:{size:10},stepSize:20}, border:{color:'#334155'}}},
      plugins:{ legend:{display:true, position:'top', align:'end', labels:{color:'#94a3b8', boxWidth:10, boxHeight:10, font:{size:10}, usePointStyle:true, padding:12}},
        tooltip:{callbacks:{label:item=>`  ${item.dataset.label}: ${item.raw?.toFixed(1)??'–'}`}, backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, bodyColor:'#94a3b8', padding:8}}},
    plugins:[{ id:'kd-zones', beforeDatasetsDraw(chart){
      const{ctx:c, chartArea:{left,right}, scales:{y}}=chart; c.save();
      c.fillStyle='rgba(239,68,68,.05)';
      c.fillRect(left, y.getPixelForValue(100), right-left, y.getPixelForValue(80)-y.getPixelForValue(100));
      c.fillStyle='rgba(34,197,94,.05)';
      c.fillRect(left, y.getPixelForValue(20), right-left, y.getPixelForValue(0)-y.getPixelForValue(20));
      c.restore();
    }}],
  });
}

export function renderOBV(canvas, klines, indicators) {
  if (!indicators?.obv) return null;
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type:'line',
    data:{ labels: thinLabels(klines), datasets:[
      { data: indicators.obv, borderColor:'#a78bfa', borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true,
        fill:{ target:'origin', above:'rgba(167,139,250,.08)', below:'rgba(167,139,250,.03)' }},
    ]},
    options:{ responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{ x:{display:false}, y:{display:true, position:'right', ticks:{color:'#64748b',font:{size:9},callback:v=>fmtVol(v)}, grid:{color:'#1e293b40'}, border:{display:false}}},
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:item=>`  OBV: ${fmtVol(item.raw)}`}, backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, bodyColor:'#94a3b8', padding:8}}},
  });
}
