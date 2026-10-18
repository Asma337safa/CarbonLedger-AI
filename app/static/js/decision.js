/* CarbonLedger AI — comparateur de décisions : recalcul en direct (aucune librairie externe). */
(function () {
  "use strict";

  var CL = window.CL;

  function qs(root, selector) { return root.querySelector(selector); }
  function qsa(root, selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }
  function text(el, value) { if (el) el.textContent = value; }
  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function formatValue(el, value) {
    if (!el) return;
    var format = el.getAttribute("data-format") || "text";
    if (value === null || value === undefined || value === "") { el.textContent = "—"; return; }
    var number = CL.toNumber(value);
    switch (format) {
      case "money": el.textContent = CL.fmtMoney(number, 2); break;
      case "money0": el.textContent = CL.fmtMoney(number, 0); break;
      case "money-signed":
        el.textContent = (number > 0 ? "+" : "") + CL.fmtMoney(number, 2);
        break;
      case "tco2e": el.textContent = CL.fmtTco2e(number); break;
      case "number": el.textContent = CL.fmtNumber(number, 2); break;
      case "number1": el.textContent = CL.fmtNumber(number, 1); break;
      case "percent-signed":
        el.textContent = (number > 0 ? "+" : "") + CL.fmtNumber(number, 1) + "\u202f%";
        break;
      default: el.textContent = String(value);
    }
  }

  function fillCells(root, container) {
    qsa(root, "[data-cell]").forEach(function (cell) {
      var key = cell.getAttribute("data-cell");
      formatValue(cell, container ? container[key] : null);
    });
  }

  // ------------------------------------------------------------------
  // Rendu des sections du comparateur
  // ------------------------------------------------------------------
  function renderFigures(figures) {
    if (!figures) return;
    qsa(document, "[data-figure]").forEach(function (el) {
      formatValue(el, figures[el.getAttribute("data-figure")]);
    });
    var pairEl = qs(document, "[data-figure-pair]");
    if (pairEl && figures.pair) pairEl.textContent = figures.pair.a + " ↔ " + figures.pair.b;
    var doubleGain = qs(document, "[data-flag='double_gain']");
    if (doubleGain) {
      if (figures.double_gain === true) {
        doubleGain.textContent = "Gain double : option la moins chère ET la moins émettrice";
        doubleGain.className = "badge badge--success";
      } else if (figures.double_gain === false) {
        doubleGain.textContent = "Surcoût à évaluer entre coût et émissions";
        doubleGain.className = "badge badge--warning";
      } else {
        doubleGain.textContent = "Données carbone insuffisantes";
        doubleGain.className = "badge badge--muted";
      }
    }
  }

  function renderOptionsTable(comparison) {
    var byKey = {};
    comparison.options.forEach(function (option) {
      // « annual_net » (coût annuel net) n'existe que dérivé de la première année.
      if (option.annual_net === undefined && (option.annual_net_costs || []).length) {
        option.annual_net = option.annual_net_costs[0];
      }
      byKey[option.key] = option;
    });
    qsa(document, "[data-option-row]").forEach(function (row) {
      var data = byKey[row.getAttribute("data-option-row")];
      if (data) fillCells(row, data);
    });
  }

  function renderPairsTable(comparison) {
    var byPair = {};
    comparison.pairs.forEach(function (pair) { byPair[pair.a_key + "|" + pair.b_key] = pair; });
    qsa(document, "[data-pair-row]").forEach(function (row) {
      var key = row.getAttribute("data-pair-row");
      var data = byPair[key];
      if (!data) return;
      fillCells(row, data);
      var interpretation = qs(row, "[data-cell='interpretation']");
      if (interpretation) interpretation.textContent = (data.interpretation_parts || []).join(" ");
    });
    var list = qs(document, "[data-pairs-list]");
    if (list) {
      list.innerHTML = "";
      comparison.pairs.forEach(function (pair) {
        var item = document.createElement("div");
        item.className = "interpretation__item";
        item.textContent = pair.a_name + " ↔ " + pair.b_name + " : " + (pair.interpretation_parts || []).join(" ");
        list.appendChild(item);
      });
    }
  }

  function renderCharts(charts) {
    if (!charts) return;
    qsa(document, "[data-chart]").forEach(function (holder) {
      var key = holder.getAttribute("data-chart");
      var svg = charts[key];
      if (svg) {
        holder.innerHTML = svg;
        holder.hidden = false;
      }
    });
  }

  function renderArbitration(arbitration) {
    if (!arbitration) return;
    text(qs(document, "[data-arbitration='title']"), arbitration.recommendation_title);
    text(qs(document, "[data-arbitration='priority']"), arbitration.priority_label);
    text(qs(document, "[data-arbitration='basis']"), arbitration.basis === "cout_etendu"
      ? "Classement sur coût étendu (émissions valorisées au prix interne du carbone)"
      : "Classement sur coûts financiers saisis");
    text(qs(document, "[data-arbitration='method']"), arbitration.method_note);

    var paragraphs = qs(document, "[data-arbitration='paragraphs']");
    if (paragraphs) {
      paragraphs.innerHTML = "";
      arbitration.recommendation_paragraphs.forEach(function (entry) {
        var p = document.createElement("p");
        p.textContent = entry;
        paragraphs.appendChild(p);
      });
    }

    var caveats = qs(document, "[data-arbitration='caveats']");
    if (caveats) {
      caveats.innerHTML = "";
      arbitration.caveats.forEach(function (entry) {
        var li = document.createElement("li");
        li.textContent = entry;
        caveats.appendChild(li);
      });
    }

    var ranking = qs(document, "[data-arbitration='ranking']");
    if (ranking) {
      ranking.innerHTML = "";
      arbitration.ranking.forEach(function (assessment, index) {
        var card = document.createElement("div");
        card.className = "assessment" + (index === 0 ? " assessment--first" : "");
        var advantages = (assessment.advantages || []).map(function (line) { return "<li>" + escapeHtml(line) + "</li>"; }).join("");
        var disadvantages = (assessment.disadvantages || []).map(function (line) { return "<li>" + escapeHtml(line) + "</li>"; }).join("");
        var facts = (assessment.facts || []).map(function (line) { return "<li>" + escapeHtml(line) + "</li>"; }).join("");
        card.innerHTML =
          '<div class="assessment__head">' +
            '<span class="assessment__name">' + escapeHtml(assessment.name) + "</span>" +
            '<span class="assessment__rank">Rang ' + assessment.rank +
            (assessment.composite_score ? " · score combiné " + escapeHtml(assessment.composite_score) + "/100" : "") +
            "</span>" +
          "</div>" +
          '<div class="assessment__lists">' +
            "<div><h4>Avantages</h4><ul>" + (advantages || "<li>Aucun avantage distinctif identifié dans les données saisies.</li>") + "</ul></div>" +
            "<div><h4>Points de vigilance</h4><ul>" + (disadvantages || "<li>Aucun point de vigilance identifié.</li>") + "</ul></div>" +
          "</div>" +
          (facts ? '<ul class="assessment__facts">' + facts + "</ul>" : "");
        ranking.appendChild(card);
      });
    }
  }

  function renderMissingData(items) {
    var holder = qs(document, "[data-missing-data]");
    if (!holder) return;
    holder.innerHTML = "";
    if (!items || !items.length) {
      var ok = document.createElement("p");
      ok.className = "muted";
      ok.textContent = "Aucune donnée manquante critique détectée pour cette comparaison.";
      holder.appendChild(ok);
      return;
    }
    items.forEach(function (item) {
      var node = document.createElement("div");
      node.className = "notice notice--" + (item.level || "info");
      var title = document.createElement("strong");
      title.className = "notice__title";
      title.textContent = item.message;
      var hint = document.createElement("span");
      hint.className = "notice__message";
      hint.textContent = item.hint || "";
      node.appendChild(title);
      node.appendChild(hint);
      holder.appendChild(node);
    });
  }

  function renderScenarios(scenarios) {
    var body = qs(document, "[data-scenarios-body]");
    if (!body || !scenarios) return;
    body.innerHTML = "";
    scenarios.forEach(function (scenario) {
      (scenario.summary_lines || []).forEach(function (line, index) {
        var row = document.createElement("tr");
        var cellName = document.createElement("td");
        cellName.innerHTML = "<strong>" + escapeHtml(scenario.label) + "</strong>" +
          '<div class="muted small">' + escapeHtml(scenario.params_description || "") + "</div>";
        var cellLine = document.createElement("td");
        cellLine.textContent = line;
        row.appendChild(cellName);
        row.appendChild(cellLine);
        if (index === 0) cellName.setAttribute("rowspan", String((scenario.summary_lines || []).length));
        body.appendChild(row);
      });
      if (!(scenario.summary_lines || []).length) {
        var empty = document.createElement("tr");
        empty.innerHTML = "<td><strong>" + escapeHtml(scenario.label) + "</strong></td><td class=\"muted\">Aucun changement chiffré par rapport au scénario de base.</td>";
        body.appendChild(empty);
      }
    });
  }

  function renderInterpretations(comparison, formula) {
    var list = qs(document, "[data-pairs-list]");
    if (!list) return;
    renderPairsTable(comparison);
    var formulaEl = qs(document, "[data-formula]");
    if (formulaEl && formula) formulaEl.textContent = formula;
  }

  function renderAnalysis(analysis) {
    if (!analysis) return;
    renderFigures(analysis.key_figures);
    if (analysis.comparison) {
      renderOptionsTable(analysis.comparison);
      renderInterpretations(analysis.comparison, analysis.formula);
    }
    renderCharts(analysis.charts);
    renderArbitration(analysis.arbitration);
    renderMissingData(analysis.missing_data);
    if (analysis.scenarios && analysis.scenarios.length) renderScenarios(analysis.scenarios);
    var sensitivityHolder = qs(document, "[data-sensitivity-summary]");
    if (sensitivityHolder && analysis.sensitivity_lines) {
      sensitivityHolder.innerHTML = "";
      analysis.sensitivity_lines.forEach(function (line) {
        var p = document.createElement("p");
        p.textContent = line;
        sensitivityHolder.appendChild(p);
      });
    }
  }

  // ------------------------------------------------------------------
  // Formulaire de projet : aperçu en direct
  // ------------------------------------------------------------------
  function readOptionCards() {
    var cards = qsa(document, "#options-container .option-card");
    return cards.map(function (card, index) {
      function val(name) {
        var input = qs(card, "[name='" + name + "']");
        return input ? input.value : "";
      }
      return {
        key: val("option_key") || ("option_" + (index + 1)),
        name: val("option_name") || ("Option " + (index + 1)),
        supplier: val("option_supplier"),
        purchase_cost: val("option_purchase_cost"),
        transport_cost: val("option_transport_cost"),
        annual_opex: val("option_annual_opex"),
        annual_energy_share_pct: val("option_annual_energy_share_pct"),
        annual_maintenance: val("option_annual_maintenance"),
        annual_savings: val("option_annual_savings"),
        useful_life_years: val("option_useful_life_years"),
        annual_emissions_kg: val("option_annual_emissions_kg"),
        emissions_basis: val("option_emissions_basis"),
        emissions_source_note: val("option_emissions_source_note"),
        confidence: val("option_confidence") || "moyenne",
        notes: val("option_notes"),
      };
    });
  }

  function readProjectMeta() {
    function val(selector) {
      var input = qs(document, selector);
      return input ? input.value : "";
    }
    return {
      horizon_years: val("#field-horizon_years") || "5",
      discount_rate_pct: val("#field-discount_rate_pct") || "0",
      internal_carbon_price: val("#field-internal_carbon_price") || "0",
      priority: val("#field-priority") || "equilibre",
    };
  }

  function initProjectForm() {
    var form = qs(document, "#project-form");
    if (!form) return;
    var container = qs(document, "#options-container");
    var template = qs(document, "#option-template");
    var preview = qs(document, "#preview");
    var status = qs(document, "#preview-status");
    var timer = null;

    function updateRemoveButtons() {
      var cards = qsa(container, ".option-card");
      cards.forEach(function (card) {
        var button = qs(card, "[data-remove-option]");
        if (button) button.hidden = cards.length <= 2;
      });
      qsa(container, ".option-card").forEach(function (card, index) {
        var title = qs(card, ".option-card__title");
        if (title) title.textContent = "Option " + (index + 1);
      });
    }

    function addCard() {
      if (!template) return;
      var fragment = template.content.cloneNode(true);
      container.appendChild(fragment);
      updateRemoveButtons();
      recomputeSoon();
    }

    function recomputeSoon() {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(recompute, 420);
    }

    function recompute() {
      var options = readOptionCards();
      if (options.length < 2) {
        if (status) status.textContent = "Ajoutez au moins deux options pour lancer la comparaison.";
        return;
      }
      var meta = readProjectMeta();
      if (status) status.textContent = "Calcul en cours…";
      CL.postJSON("/api/projects/compute", {
        options: options,
        horizon_years: meta.horizon_years,
        internal_carbon_price: meta.internal_carbon_price,
        discount_rate_pct: meta.discount_rate_pct,
        priority: meta.priority,
        with_scenarios: false,
        with_sensitivity: false,
        with_charts: true,
      }).then(function (data) {
        if (status) status.textContent = "Aperçu recalculé à partir des valeurs saisies (rien n'est enregistré).";
        renderAnalysis(data.analysis);
        if (preview) preview.hidden = false;
      }).catch(function (error) {
        if (status) status.textContent = error.message;
      });
    }

    form.addEventListener("input", function (event) {
      if (event.target.closest("#options-container") || event.target.closest("#project-meta")) recomputeSoon();
    });
    form.addEventListener("change", function (event) {
      if (event.target.closest("#options-container") || event.target.closest("#project-meta")) recomputeSoon();
    });
    form.addEventListener("click", function (event) {
      if (event.target.closest("[data-add-option]")) { event.preventDefault(); addCard(); }
      var remove = event.target.closest("[data-remove-option]");
      if (remove) {
        event.preventDefault();
        var card = remove.closest(".option-card");
        if (qsa(container, ".option-card").length > 2 && card) card.remove();
        updateRemoveButtons();
        recomputeSoon();
      }
    });

    updateRemoveButtons();
    recompute();
  }

  // ------------------------------------------------------------------
  // Page de détail : priorité, scénarios et sensibilité en direct
  // ------------------------------------------------------------------
  function initDecisionDetail() {
    var page = qs(document, "#decision-page");
    if (!page) return;
    var projectId = page.getAttribute("data-project-id");
    var label = qs(document, "#scenario-active-label");
    var timer = null;

    function compute(payload) {
      CL.postJSON("/api/decisions/" + projectId + "/compute", payload).then(function (data) {
        renderAnalysis(data.analysis);
        if (label && data.analysis.scenarios && payload.params) {
          var description = "";
          try {
            description = "Scénario actif : " + (payload.label || "personnalisé");
          } catch (error) { description = "Scénario recalculé"; }
          label.textContent = description + " — les chiffres affichés sont recalculés, rien n'est enregistré.";
        }
      }).catch(function (error) {
        CL.flash("danger", error.message);
      });
    }

    function priorityPayload() {
      var select = qs(document, "#priority-select");
      return {
        priority: select ? select.value : "equilibre",
        with_scenarios: true,
        with_sensitivity: true,
        with_charts: true,
      };
    }

    var prioritySelect = qs(document, "#priority-select");
    if (prioritySelect) {
      prioritySelect.addEventListener("change", function () {
        var button = qs(document, "#priority-apply");
        if (!button) compute(priorityPayload());
      });
    }
    var applyButton = qs(document, "#priority-apply");
    if (applyButton) {
      applyButton.addEventListener("click", function (event) {
        event.preventDefault();
        compute(priorityPayload());
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

    function updateParamLabels() {
      qsa(document, "[data-param]").forEach(function (input) {
        var out = qs(document, "[data-param-output='" + input.getAttribute("data-param") + "']");
        if (out) out.textContent = (CL.toNumber(input.value) > 0 ? "+" : "") + CL.fmtNumber(CL.toNumber(input.value), 0) + "\u202f" +
          (input.getAttribute("data-param") === "lifetime_delta_years" ? "an(s)" : "%");
      });
    }

    qsa(document, "[data-param]").forEach(function (input) {
      input.addEventListener("input", updateParamLabels);
      input.addEventListener("input", function () {
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          var payload = priorityPayload();
          payload.params = readParams();
          payload.with_scenarios = false;
          payload.label = payload.params.label;
          compute(payload);
        }, 520);
      });
    });
    updateParamLabels();

    var resetButton = qs(document, "#sim-reset");
    if (resetButton) {
      resetButton.addEventListener("click", function (event) {
        event.preventDefault();
        qsa(document, "[data-param]").forEach(function (input) { input.value = "0"; });
        var nameInput = qs(document, "#sim-name");
        if (nameInput) nameInput.value = "";
        updateParamLabels();
        var payload = priorityPayload();
        payload.params = null;
        compute(payload);
      });
    }

    var saveButton = qs(document, "#save-form-toggle");
    if (saveButton) {
      saveButton.addEventListener("click", function (event) {
        event.preventDefault();
        var form = qs(document, "#save-form");
        if (form) {
          form.hidden = !form.hidden;
          if (!form.hidden) {
            qsa(document, "#save-form [data-param]").forEach(function (input) {
              var target = qs(document, "#scenario-form [data-param='" + input.getAttribute("data-param") + "']");
              if (target) target.value = input.value;
            });
            var nameTarget = qs(document, "#scenario-form [name='name']");
            var nameSource = qs(document, "#sim-name");
            if (nameTarget && nameSource && nameSource.value) nameTarget.value = nameSource.value;
          }
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initProjectForm();
    initDecisionDetail();
  });

  window.CLDecision = { renderAnalysis: renderAnalysis, renderScenarios: renderScenarios };
})();
