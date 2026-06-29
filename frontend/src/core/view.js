// View 抽象基底類別。
//
// 所有頂層 view（個股分析、潛力選股、策略回測…）與內層子 view 都應繼承本類別，
// 由 TabController / Router 統一驅動生命週期，避免每個 view 自己土法煉鋼控制顯示/隱藏、
// 重複初始化、或忘記釋放 Chart instance 造成記憶體洩漏。
//
// 生命週期（呼叫順序）：
//   1. constructor(deps)        ← 依賴注入（services、event bus 等），不碰 DOM
//   2. mount(container)         ← 第一次進入時：建立 DOM、Chart instance、訂閱事件
//   3. activate(params)         ← 每次切回來時：刷新資料；mount 之後一定會接 activate
//   4. deactivate()             ← 切走時：暫停輪詢、隱藏容器；DOM 保留以便快速回返
//   5. unmount()                ← 真正銷毀：destroy charts、unsubscribe、清空 DOM
//
// 子類別只需 override 用得到的階段；用不到的階段保留 no-op 預設即可。

export class View {
  constructor() {
    this.container = null;
    this.mounted = false;
    this.active = false;
  }

  mount(container) {
    this.container = container;
    this.mounted = true;
  }

  activate(_params = {}) {
    this.active = true;
    if (this.container) this.container.classList.remove('hidden');
  }

  deactivate() {
    this.active = false;
    if (this.container) this.container.classList.add('hidden');
  }

  unmount() {
    if (this.container) this.container.innerHTML = '';
    this.mounted = false;
  }
}
