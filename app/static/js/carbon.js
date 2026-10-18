/* CarbonLedger AI — aide au calcul carbone : rappel du facteur et aperçu (quantité × facteur). */
(function () {
  "use strict";

  var CL = window.CL;

  function qs(root, selector) { return root.querySelector(selector); }

  function selectedFactor(select) {
    if (!select || !select.value) return null;
    var option = select.options[select.selectedIndex];
    if (!option) return null;
    return {
      id: select.value,
      unit: option.getAttribute("data-unit") || "",
      value: option.getAttribute("data-value") || "",
      code: option.getAttribute("data-code") || "",
      label: option.getAttribute("data-label") || "",
      source: option.getAttribute("data-source") || "",
      scope: option.getAttribute("data-scope") || "",
      method: option.getAttribute("data-method") || "",
      confidence: option.getAttribute("data-confidence") || "",
      validFrom: option.getAttribute("data-valid-from") || "",
      validUntil: option.getAttribute("data-valid-until") || "",
      note: option.getAttribute("data-note") || "",
    };
  }

  function init() {
    var form = qs(document, ".js-carbon-form");
    if (!form) return;
    var select = qs(form, "[data-factor-select]") || qs(form, "[name='factor_id']") || qs(form, "[name='emission_factor_id']");
    var hint = qs(document, "#factor-hint");
    var output = qs(document, "#carbon-preview");
    var button = qs(document, "#carbon-preview-button");

    function updateHint() {
      if (!hint) return;
      var factor = selectedFactor(select);
      if (!factor) { hint.hidden = true; hint.innerHTML = ""; return; }
      hint.hidden = false;
      hint.innerHTML = "";
      var strong = document.createElement("strong");
      strong.textContent = factor.code + " — " + factor.label + " ";
      var details = document.createElement("span");
      details.textContent = "Valeur : " + factor.value + " kgCO₂e/" + factor.unit +
        " · Source : " + (factor.source || "non documentée") +
        (factor.scope ? " · " + factor.scope : "") +
        (factor.method ? " · Méthode : " + factor.method : "") +
        (factor.confidence ? " · Confiance : " + factor.confidence : "") +
        (factor.validFrom || factor.validUntil ? " · Validité : " + (factor.validFrom || "—") + " → " + (factor.validUntil || "—") : "") +
        (factor.note ? " · " + factor.note : "");
      hint.appendChild(strong);
      hint.appendChild(details);
    }

    function preview() {
      if (!output) return;
      var quantity = qs(form, "[name='quantity']");
      var unit = qs(form, "[name='unit']");
      var factor = selectedFactor(select);
      output.hidden = false;
      output.innerHTML = "";
      if (!quantity || CL.toNumber(quantity.value) === null) {
        output.innerHTML = '<div class="notice notice--attention"><strong class="notice__title">Quantité manquante</strong><span class="notice__message">Saisissez une quantité d\'activité positive pour lancer l\'aperçu.</span></div>';
        return;
      }
      if (!factor) {
        output.innerHTML = '<div class="notice notice--attention"><strong class="notice__title">Aucun facteur sélectionné</strong><span class="notice__message">Le carbone n\'est pas estimé sans facteur d\'émission documenté : aucun facteur n\'est attribué automatiquement.</span></div>';
        return;
      }
      output.innerHTML = '<p class="muted small">Calcul en cours…</p>';
      var payload = { quantity: quantity.value, unit: unit ? unit.value : "", factor_id: factor.id };
      CL.postJSON("/api/emissions/preview", payload).then(function (data) {
        output.innerHTML = "";
        var formula = document.createElement("div");
        formula.className = "formula";
        formula.textContent = data.formula;
        var summary = document.createElement("p");
        summary.className = "mt-1";
        summary.textContent = "Soit " + CL.fmtNumber(data.tonnes, 3) + "\u202f t CO₂e (" + CL.fmtNumber(data.kgco2e, 3) + " kg CO₂e). Quantité convertie : " +
          CL.fmtNumber(data.converted_quantity, 4) + " " + data.converted_unit + ".";
        var source = document.createElement("p");
        source.className = "muted small";
        source.textContent = "Source du facteur : " + (data.factor.source || "non documentée") +
          " · confiance " + data.factor.confidence + " · validité " +
          (data.factor.valid_from || "—") + " → " + (data.factor.valid_until || "—") +
          ". Estimation : ce résultat n'est pas une mesure, il sera classé selon la méthode du facteur.";
        output.appendChild(formula);
        output.appendChild(summary);
        output.appendChild(source);
      }).catch(function (error) {
        output.innerHTML = '<div class="notice notice--danger"><strong class="notice__title">Aperçu impossible</strong><span class="notice__message">' +
          error.message + "</span></div>";
      });
    }

    if (select) {
      select.addEventListener("change", updateHint);
      updateHint();
    }
    if (button) button.addEventListener("click", function (event) { event.preventDefault(); preview(); });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
