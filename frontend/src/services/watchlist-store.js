// 自選股的 localStorage 封裝 + in-memory 報價快取。
//
// 對外只暴露 add/remove/list/setQuote 等明確操作；DOM 渲染由訂閱者
// （sidebar component）監聽 'change' 事件後自行重繪，store 不碰 DOM。

import { normalizeTicker } from './ticker-utils.js';

const STORAGE_KEY = 'stock-insights-watchlist';
const DEFAULT_LIST = ['AAPL', 'TSLA', 'NVDA'];

export class WatchlistStore {
  constructor() {
    this._tickers = this._load();
    this._quotes = {};          // symbol → quote payload
    this._handlers = new Set(); // change handlers
  }

  list() { return [...this._tickers]; }
  quotes() { return { ...this._quotes }; }
  has(ticker) { return this._tickers.includes(ticker); }

  add(rawTicker) {
    const t = normalizeTicker(rawTicker);
    if (!t || this._tickers.includes(t)) return false;
    this._tickers.push(t);
    this._save();
    this._emit();
    return true;
  }

  remove(ticker) {
    const before = this._tickers.length;
    this._tickers = this._tickers.filter(x => x !== ticker);
    if (this._tickers.length === before) return false;
    delete this._quotes[ticker];
    this._save();
    this._emit();
    return true;
  }

  setQuotes(quotes) {
    // quotes: Array<{ symbol, current_price, change, change_pct, error? }>
    this._quotes = {};
    for (const q of quotes) if (!q.error) this._quotes[q.symbol] = q;
    this._emit();
  }

  setQuote(symbol, quote) {
    this._quotes[symbol] = quote;
    this._emit();
  }

  onChange(handler) {
    this._handlers.add(handler);
    return () => this._handlers.delete(handler);
  }

  _emit() {
    for (const h of this._handlers) {
      try { h({ tickers: this.list(), quotes: this.quotes() }); }
      catch (err) { console.error('[watchlist-store] handler threw:', err); }
    }
  }

  _load() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [...DEFAULT_LIST]; }
    catch { return [...DEFAULT_LIST]; }
  }

  _save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this._tickers));
  }
}
