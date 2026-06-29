// 通用 placeholder view：給尚未實作的功能 view 用。
//
// 用 placeholder 而非「之後再建檔」的好處：
//   - router 可以直接導向（URL 已可用、可分享）
//   - header 的「目前 view」邏輯被測試到
//   - 視覺上明示「功能開發中」而非 404
//
// 等該 view 實作完成時，main.js 把 placeholder 換成真正的 View instance 即可，
// 其餘地方（router、tab bar、header）不需動。

import { View } from '../core/view.js';

export class PlaceholderView extends View {
  constructor({ title, description, eta = null }) {
    super();
    this._title = title;
    this._desc = description;
    this._eta = eta;
  }

  mount(container) {
    super.mount(container);
    const etaHtml = this._eta ? `<p class="text-xs text-slate-600 mt-2">預計上線：${this._eta}</p>` : '';
    container.innerHTML = `
      <div class="bg-slate-800 rounded-2xl p-12 border border-slate-700 border-dashed text-center fade-in">
        <div class="text-5xl mb-4 opacity-50">🚧</div>
        <h2 class="text-lg font-semibold text-slate-300 mb-2">${this._title}</h2>
        <p class="text-sm text-slate-500 max-w-md mx-auto">${this._desc}</p>
        ${etaHtml}
      </div>
    `;
  }
}
