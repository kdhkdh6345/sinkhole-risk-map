const fs = require('fs');
let html = fs.readFileSync('web/index.html', 'utf8');

// Update CSS
html = html.replace(
  "    #side-panel {\n      position: fixed;\n      top: calc(var(--header-h) + 12px); right: 12px;\n      width: var(--panel-w); z-index: 900;\n      display: flex; flex-direction: column; gap: 10px;\n      pointer-events: none;\n    }",
  `    #left-panel, #right-panel {
      position: fixed;
      top: calc(var(--header-h) + 12px);
      width: var(--panel-w); z-index: 900;
      display: flex; flex-direction: column; gap: 10px;
      pointer-events: none;
      max-height: calc(100vh - var(--header-h) - 24px);
      overflow-y: auto;
    }
    #left-panel::-webkit-scrollbar, #right-panel::-webkit-scrollbar {
      width: 6px;
    }
    #left-panel::-webkit-scrollbar-thumb, #right-panel::-webkit-scrollbar-thumb {
      background: rgba(255,255,255,0.2);
      border-radius: 3px;
    }
    #left-panel { left: 12px; }
    #right-panel { right: 12px; }`
);

html = html.replace(
  "      #side-panel {\n        top: auto; bottom: 12px; right: 12px; left: 12px;",
  "      #left-panel, #right-panel {\n        top: auto; bottom: 12px; right: 12px; left: 12px; max-height: 25vh;"
);

// Split side-panel into left-panel and right-panel
// Existing side-panel content starts with <aside id="side-panel">
// We will replace it with:
// <aside id="left-panel">
//   ... (Data sources, Sim, Theme, Layers)
// </aside>
// <aside id="right-panel">
//   ... (Legend, LLM panel)
// </aside>
