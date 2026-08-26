import sys

with open('web/index.html', 'r') as f:
    code = f.read()

old_css = """    #side-panel {
      position: fixed;
      top: calc(var(--header-h) + 12px); right: 12px;
      width: var(--panel-w); z-index: 900;
      display: flex; flex-direction: column; gap: 10px;
      pointer-events: none;
    }"""
new_css = """    #left-panel, #right-panel {
      position: fixed;
      top: calc(var(--header-h) + 12px);
      width: var(--panel-w); z-index: 900;
      display: flex; flex-direction: column; gap: 10px;
      pointer-events: none;
      max-height: calc(100vh - var(--header-h) - 24px);
      overflow-y: auto;
    }
    #left-panel::-webkit-scrollbar, #right-panel::-webkit-scrollbar {
      width: 4px;
    }
    #left-panel::-webkit-scrollbar-thumb, #right-panel::-webkit-scrollbar-thumb {
      background: rgba(255,255,255,0.2);
      border-radius: 2px;
    }
    #left-panel { left: 12px; }
    #right-panel { right: 12px; }"""
code = code.replace(old_css, new_css)

old_media = """      #side-panel {
        top: auto; bottom: 12px; right: 12px; left: 12px;
        width: auto;
        flex-direction: row; overflow-x: auto;
        flex-wrap: nowrap;
        gap: 8px;
      }"""
new_media = """      #left-panel, #right-panel {
        top: auto; bottom: 12px; right: 12px; left: 12px;
        width: auto;
        flex-direction: row; overflow-x: auto; overflow-y: hidden;
        flex-wrap: nowrap;
        gap: 8px;
        max-height: 25vh;
      }
      #left-panel { bottom: calc(25vh + 24px); } /* 좌측 패널을 모바일에서 위로 올림 */"""
code = code.replace(old_media, new_media)

with open('web/index.html', 'w') as f:
    f.write(code)

print("CSS Patched.")
