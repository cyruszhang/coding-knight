// Real code completion for the kid-facing editor, via Pyodide (WASM
// CPython) + Jedi (static analysis). Runs in a module Worker -- this is
// required, not a style choice: Pyodide's own loader detects a classic
// worker and throws "Classic web workers are not supported" (confirmed
// directly before writing this file). A classic-worker + importScripts()
// approach will not work here.
//
// Pyodide's distribution removes the `turtle` module entirely (browser
// limitation -- no display backend), so this worker is completion-only.
// It never executes the kid's actual program; Skulpt still does that,
// unchanged, elsewhere in the app.
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.6/full/pyodide.mjs";

const pyodideReady = (async () => {
  const pyodide = await loadPyodide();
  await pyodide.loadPackage(["jedi"]);
  pyodide.runPython("import jedi");
  postMessage({ type: "ready" });
  return pyodide;
})();

onmessage = async (e) => {
  if (e.data.type !== "complete") return;
  const { id, source, line, column } = e.data;
  const pyodide = await pyodideReady;
  try {
    pyodide.globals.set("_src", source);
    pyodide.globals.set("_line", line);
    pyodide.globals.set("_col", column);
    // Docstring truncated here (one line, 80 chars) rather than in the
    // main thread -- keeps the postMessage payload small.
    const raw = pyodide.runPython(`
      [(c.name, c.type, (c.docstring() or "").split(chr(10))[0][:80])
       for c in jedi.Script(_src).complete(_line, _col)]
    `);
    postMessage({ type: "complete-result", id, completions: raw.toJs() });
  } catch (err) {
    // A transient bad parse mid-keystroke should never break the editor
    // -- just answer with no suggestions for this one request.
    postMessage({ type: "complete-result", id, completions: [] });
  }
};
