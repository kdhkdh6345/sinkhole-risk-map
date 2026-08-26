import sys

with open('web/index.html', 'r') as f:
    code = f.read()

code = code.replace(
    "      display: flex; flex-direction: column; gap: 10px;\n      pointer-events: none;",
    "      display: flex; flex-direction: column; gap: 10px;\n      pointer-events: none; /* Let scroll events pass through empty space */"
)
# Wait, actually, let's make a container inside left-panel?
# No, let's just make the scrollbar work. If we use pointer-events: none, the scrollbar thumb is NOT clickable.
# If we set pointer-events: auto, it IS clickable. Let's set it to auto.
code = code.replace(
    "      display: flex; flex-direction: column; gap: 10px;\n      pointer-events: none;",
    "      display: flex; flex-direction: column; gap: 10px;\n      pointer-events: auto;"
)

# In mobile view, make sure it doesn't block the whole screen
old_media = """      #left-panel, #right-panel {
        top: auto; bottom: 12px; right: 12px; left: 12px;
        width: auto;
        flex-direction: row; overflow-x: auto; overflow-y: hidden;
        flex-wrap: nowrap;
        gap: 8px;
        max-height: 25vh;
      }"""
new_media = """      #left-panel, #right-panel {
        top: auto; bottom: 12px; right: 12px; left: 12px;
        width: auto;
        flex-direction: row; overflow-x: auto; overflow-y: hidden;
        flex-wrap: nowrap;
        gap: 8px;
        max-height: 25vh;
        pointer-events: auto;
      }"""
code = code.replace(old_media, new_media)

with open('web/index.html', 'w') as f:
    f.write(code)

print("Pointer events patched.")
