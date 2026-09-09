// Test-fixture-only controls. The checked page uses actual server-rendered UI.
(() => {
  "use strict";
  const button = document.getElementById("rehearsal-run-axe");
  const status = document.getElementById("rehearsal-axe-status");
  const output = document.getElementById("rehearsal-axe-results");
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Checking rendered page…";
    output.textContent = "";
    try {
      const result = await window.axe.run(
        { exclude: [["#rehearsal-accessibility"]] },
        { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } },
      );
      output.textContent = JSON.stringify({
        violations: result.violations.map(({ id, impact, help, nodes }) => ({
          id, impact, help,
          nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })),
        })),
        incomplete: result.incomplete.map(({ id, nodes }) => ({
          id, targets: nodes.map(({ target }) => target),
        })),
        passes: result.passes.length,
      }, null, 2);
      status.textContent = `Check complete: ${result.violations.length} violations; ` +
        `${result.incomplete.length} rules need manual review. Not comprehensive acceptance.`;
    } catch (_error) {
      status.textContent = "Accessibility analysis unavailable. No acceptance result.";
    } finally {
      button.disabled = false;
    }
  });
})();
