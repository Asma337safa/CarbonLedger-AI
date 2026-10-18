/* CarbonLedger AI — page Simulations : hypothèses mobiles, recalcul immédiat. */
(function () {
  "use strict";

  var CL = window.CL;

  var PRESETS = {
    base: { energy_price_delta_pct: 0, transport_delta_pct: 0, savings_delta_pct: 0, activity_volume_delta_pct: 0, emission_factor_delta_pct: 0, lifetime_delta_years: 0 },
    optimiste: { energy_price_delta_pct: -10, transport_delta_pct: -10, savings_delta_pct: 10, activity_volume_delta_pct: 0, emission_factor_delta_pct: -5, lifetime_delta_years: 0 },
    defavorable: { energy_price_delta_pct: 15, transport_delta_pct: 15, savings_delta_pct: -20, activity_volume_delta_pct: 0, emission_factor_delta_pct: 10, lifetime_delta_years: 0 },
  };

  function qs(root, selector) { return root.querySelector(selector); }
  function qsa(root, selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }

  function init() {
    var page = qs(document, "#sim-page");
    if (!page) return;
    var projectId = page.getAttribute("data-project-id");
    var status = qs(document, "#sim-status");
    var timer = null;

    function updateLabels() {
      qsa(document, "[data-param]").forEach(function (input) {
        var out = qs(document, "[data-param-output='" + input.getAttribute("data-param") + "']");
        if (!out) return;
        var value = CL.toNumber(input.value) || 0;
        var unit = input.getAttribute("data-param") === "lifetime_delta_years" ? " an(s)" : "\u202f%";
        out.textContent = (value > 0 ? "+" : "") + CL.fmtNumber(value, 0) + unit;
      });
    }

    function readParams() {
      var params = { label: "Scénario personnalisé" };
      qsa(document, "[data-param]").forEach(function (input) {
        params[input.getAttribute("data-param")] = input.value;
      });
      var nameInput = qs(document, "#sim-name");
      if (nameInput && nameInput.value.trim()) params.label = nameInput.value.trim();
      return params;
    }

    function run() {
      if (!projectId) return;
      var prioritySelect = qs(document, "#sim-priority");
      if (status) status.textContent = "Calcul en cours…";
      CL.postJSON("/simulations/" + projectId + "/simulate", {
        params: readParams(),
        priority: prioritySelect ? prioritySelect.value : "equilibre",
        with_sensitivity: true,
        with_charts: true,
      }).then(function (data) {
        window.CLDecision.renderAnalysis(data.analysis);
        if (status) {
          status.textContent = "Hypothèses appliquées : " + data.params_description +
            ". Chiffres recalculés par le moteur, rien n'est enregistré.";
        }
      }).catch(function (error) {
        if (status) status.textContent = "";
        CL.flash("danger", error.message);
      });
    }

    function runSoon() {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(run, 420);
    }

    qsa(document, "[data-param]").forEach(function (input) {
      input.addEventListener("input", function () { updateLabels(); runSoon(); });
    });

    var prioritySelect = qs(document, "#sim-priority");
    if (prioritySelect) prioritySelect.addEventListener("change", run);

    var runButton = qs(document, "#sim-run");
    if (runButton) runButton.addEventListener("click", function (event) { event.preventDefault(); run(); });

    var resetButton = qs(document, "#sim-reset");
    if (resetButton) {
      resetButton.addEventListener("click", function (event) {
        event.preventDefault();
        applyPreset("base");
      });
    }

    qsa(document, "[data-preset]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.preventDefault();
        applyPreset(button.getAttribute("data-preset"));
      });
    });

    function applyPreset(kind) {
      var preset = PRESETS[kind] || PRESETS.base;
      qsa(document, "[data-param]").forEach(function (input) {
        var name = input.getAttribute("data-param");
        if (Object.prototype.hasOwnProperty.call(preset, name)) input.value = String(preset[name]);
      });
      var nameInput = qs(document, "#sim-name");
      if (nameInput) nameInput.value = kind === "base" ? "" : (kind === "optimiste" ? "Optimiste" : "Défavorable");
      updateLabels();
      run();
    }

    updateLabels();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
