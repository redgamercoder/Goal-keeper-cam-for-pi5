# PrintCAD — browser CAD editor for your 3D printer

A single-file, browser-based CAD editor for designing 3D-printable models, inspired by
"Claude designs a 3D-printable model in a Claude-built CAD editor". No install, no build
step — just open `index.html` in a modern browser (Chrome, Edge, Firefox).

## Features

- **3D viewport** with a 220×220 mm print bed, Z-up, millimetre units (matches your slicer)
- **Primitives**: box, cylinder, sphere, cone, torus, hex prism
- **Transform gizmo**: move / rotate / scale with snapping (W / E / R keys)
- **Boolean operations**: union, subtract, intersect (Ctrl+click to multi-select)
- **Editable parameters**: dimensions, position, rotation, scale, color per object
- **Undo/redo**, duplicate, drop-to-bed, save/load projects as JSON
- **Export binary STL** — drop the file straight into Cura / PrusaSlicer / Bambu Studio
- **Built-in AI assistant**: paste your Anthropic API key and describe a part in plain
  English ("a 40mm cube with a 20mm hole through it", "a hexagonal pencil cup with 2mm
  walls") — Claude designs it and it appears on the bed, ready to tweak and export

## Usage

1. Open `printcad/index.html` in a browser (double-click it, or serve the folder with
   `python3 -m http.server` and visit http://localhost:8000/printcad/).
   It loads three.js from a CDN, so you need internet access.
2. Add shapes from the left toolbar, position them, carve holes with **Subtract**.
3. Click **Export STL** and slice the file for your printer.

### AI assistant

The AI panel calls the Anthropic Messages API directly from your browser. Your API key
is stored only in your browser's localStorage and sent only to `api.anthropic.com`.
Get a key at https://platform.claude.com/. Tip: keep "Replace scene" checked for new
designs, uncheck it to add parts to what you already have.

## Notes

- The print bed is 220×220 mm (Ender-3 class). Models export in mm with Z up, which is
  what slicers expect — no rescaling needed.
- Subtraction shapes from the AI extend slightly past the material they cut, so
  through-holes come out clean.
