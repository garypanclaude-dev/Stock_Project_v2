// 股票代號相關純函式。零依賴，可單元測試。

export function normalizeTicker(raw) {
  const t = (raw || '').toUpperCase().trim();
  if (!t) return '';
  if (t.includes('.')) return t;
  if (/^\d+$/.test(t)) {
    if (t.length === 4 || t.length === 5) return t + '.TW';
    if (t.length === 6) return (t.startsWith('6') ? t + '.SS' : t + '.SZ');
  }
  return t;
}

// 移除市場後綴用於顯示（2330.TW → 2330）
export function stripSuffix(ticker) {
  return (ticker || '').replace(/\.(TW|SS|SZ)$/, '');
}
