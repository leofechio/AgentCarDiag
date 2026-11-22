import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

# 1. Update Mouse Handlers for Ruler
old_mousedown = """function handleCursorMouseDown(e) {
  if (!oscState.showCursors) return;
  const rect = oscState.cursorCtx.canvas.getBoundingClientRect();"""

new_mousedown = """function handleCursorMouseDown(e) {
  const rect = oscState.cursorCtx.canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  
  if (oscState.ruler.active) {
      oscState.ruler.dragging = true;
      oscState.ruler.startX = x;
      oscState.ruler.endX = x;
      return;
  }
  
  if (!oscState.showCursors) return;"""
code = code.replace(old_mousedown, new_mousedown)

old_mousemove = """function handleCursorMouseMove(e) {
  if (!oscState.showCursors) return;
  const rect = oscState.cursorCtx.canvas.getBoundingClientRect();"""

new_mousemove = """function handleCursorMouseMove(e) {
  const rect = oscState.cursorCtx.canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  
  if (oscState.ruler.active && oscState.ruler.dragging) {
      oscState.ruler.endX = x;
      if (!oscState.running) window.requestAnimationFrame(oscRenderLoop); // redraw if paused
      return;
  }
  
  if (!oscState.showCursors) return;"""
code = code.replace(old_mousemove, new_mousemove)

old_mouseup = """function handleCursorMouseUp(e) {
  if (!oscState.showCursors) return;
  oscState.cursorDragging = null;
}"""

new_mouseup = """function handleCursorMouseUp(e) {
  if (oscState.ruler.active) {
      oscState.ruler.dragging = false;
      return;
  }
  if (!oscState.showCursors) return;
  oscState.cursorDragging = null;
}"""
code = code.replace(old_mouseup, new_mouseup)


# 2. Patch trigger logic in oscRenderLoop
# Let's read what oscRenderLoop looks like
