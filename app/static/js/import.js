/* CarbonLedger AI — assistant d'importation en quatre étapes (CSV / Excel). */
(function () {
  "use strict";

  var CL = window.CL;

  function qs(root, selector) { return root.querySelector(selector); }
  function qsa(root, selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }

  var STATE = {
    batchId: null,
    columns: [],
    appFields: {},
    mapping: {},
    includeDuplicates: false,
    filename: "",
  };

  function setStep(step) {
    qsa(document, ".step").forEach(function (node) {
      var value = parseInt(node.getAttribute("data-step"), 10);
      node.classList.toggle("step--active", value === step);
      node.classList.toggle("step--done", value < step);
    });
    for (var index = 1; index <= 4; index += 1) {
      var panel = qs(document, "#step-" + index);
      if (panel) panel.hidden = index !== step;
    }
    var anchor = qs(document, "#import-wizard");
    if (anchor && anchor.scrollIntoView) anchor.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function renderPreviewTable(table, rows) {
    if (!table) return;
    var head = qs(table, "thead tr");
    var body = qs(table, "tbody");
    head.innerHTML = "";
    body.innerHTML = "";
    var columns = STATE.columns.slice(0, 12);
    columns.forEach(function (column) {
      var th = document.createElement("th");
      th.textContent = column;
      head.appendChild(th);
    });
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      columns.forEach(function (column) {
        var td = document.createElement("td");
        var value = row[column];
        td.textContent = value === null || value === undefined ? "" : String(value);
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
  }

  function buildMappingRows() {
    var holder = qs(document, "#mapping-rows");
    if (!holder) return;
    holder.innerHTML = "";
    var order = ["date", "amount_ht", "amount_ttc", "vat_amount", "category", "supplier", "description",
      "quantity", "unit", "factor_code", "emission_factor_value", "emissions_source", "verification_status"];
    order.forEach(function (fieldName) {
      var meta = STATE.appFields[fieldName] || { label: fieldName, required: false, help: "" };
      var row = document.createElement("div");
      row.className = "map-row";

      var label = document.createElement("div");
      label.className = "map-row__label";
      label.innerHTML = meta.label + (meta.required ? ' <span class="req">*</span>' : "") +
        (meta.help ? "<small>" + meta.help + "</small>" : "");

      var select = document.createElement("select");
      select.setAttribute("data-field", fieldName);
      var empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "— Non importé —";
      select.appendChild(empty);
      STATE.columns.forEach(function (column) {
        var option = document.createElement("option");
        option.value = column;
        option.textContent = column;
        if (STATE.mapping[fieldName] === column) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener("change", function () {
        if (select.value) STATE.mapping[fieldName] = select.value;
        else delete STATE.mapping[fieldName];
        renderDetectionNote();
      });

      row.appendChild(label);
      row.appendChild(select);
      holder.appendChild(row);
    });
    renderDetectionNote();
  }

  function renderDetectionNote() {
    var note = qs(document, "#mapping-note");
    if (!note) return;
    var mapped = Object.keys(STATE.mapping).length;
    note.textContent = mapped + " colonne(s) associée(s) sur " + STATE.columns.length +
      " détectée(s) dans le fichier. La date et au moins un montant (HT ou TTC) sont obligatoires.";
  }

  function renderStats(stats) {
    var holder = qs(document, "#validation-stats");
    if (!holder || !stats) return;
    var items = [
      ["Total lignes", stats.total, ""],
      ["Importables", stats.valid, "ok"],
      ["Erreurs", stats.errors, stats.errors ? "bad" : "ok"],
      ["Avertissements", stats.warnings, stats.warnings ? "warn" : "ok"],
      ["Doublons", stats.duplicates, stats.duplicates ? "warn" : "ok"],
      ["Avec carbone estimé", stats.with_carbon, "ok"],
      ["Sans carbone", stats.without_carbon, stats.without_carbon ? "warn" : "ok"],
    ];
    holder.innerHTML = "";
    items.forEach(function (item) {
      var node = document.createElement("div");
      node.className = "drum__item drum" + (item[2] ? "--" + item[2] : "");
      node.innerHTML = '<div class="drum__value">' + CL.fmtNumber(item[1], 0) + '</div><div class="muted small">' + item[0] + "</div>";
      holder.appendChild(node);
    });
  }

  function renderIssues(issues) {
    var body = qs(document, "#issues-body");
    if (!body) return;
    body.innerHTML = "";
    (issues || []).forEach(function (issue) {
      var row = document.createElement("tr");
      var level = issue.level === "erreur" ? "danger" : "warning";
      row.innerHTML = "<td>" + issue.row + "</td>" +
        '<td><span class="badge badge--' + level + '">' + issue.level + "</span></td>" +
        "<td>" + (issue.field || "") + "</td>" +
        "<td>" + issue.message + "</td>";
      body.appendChild(row);
    });
    var empty = qs(document, "#issues-empty");
    if (empty) empty.hidden = (issues || []).length > 0;
  }

  function renderValidationPreview(preview) {
    var body = qs(document, "#validation-body");
    if (!body) return;
    body.innerHTML = "";
    (preview || []).forEach(function (row) {
      var tr = document.createElement("tr");
      var level = row.status === "erreur" ? "danger" : (row.status === "ok" ? "success" : "warning");
      var carbon = row.carbon === null || row.carbon === undefined ? "—" : CL.fmtNumber(row.carbon, 3) + " kg";
      tr.innerHTML = "<td>" + row.line + "</td>" +
        '<td><span class="badge badge--' + level + '">' + row.status + "</span></td>" +
        "<td>" + row.date + "</td>" +
        "<td>" + row.supplier + "</td>" +
        "<td>" + row.description + "</td>" +
        "<td class=\"num\">" + row.amount_ht + "</td>" +
        "<td class=\"num\">" + row.amount_ttc + "</td>" +
        "<td>" + row.category + "</td>" +
        '<td class="num">' + carbon + "</td>";
      body.appendChild(tr);
    });
  }

  function collectMapping() {
    var mapping = {};
    qsa(document, "[data-field]").forEach(function (select) {
      if (select.value) mapping[select.getAttribute("data-field")] = select.value;
    });
    return mapping;
  }

  function init() {
    var wizard = qs(document, "#import-wizard");
    if (!wizard) return;

    var meta = qs(document, "#import-meta");
    if (meta) {
      try {
        STATE.appFields = JSON.parse(meta.getAttribute("data-app-fields") || "{}");
      } catch (error) {
        STATE.appFields = {};
      }
    }
    setStep(1);
    var fileInput = qs(document, "#import-file");
    var uploadButton = qs(document, "#upload-button");
    if (uploadButton) {
      uploadButton.addEventListener("click", function (event) {
        event.preventDefault();
        if (!fileInput || !fileInput.files.length) {
          CL.flash("warning", "Sélectionnez d'abord un fichier CSV ou Excel.");
          return;
        }
        var data = new FormData();
        data.append("file", fileInput.files[0]);
        CL.setBusy(uploadButton, true);
        CL.postForm("/api/imports/upload", data).then(function (payload) {
          STATE.batchId = payload.batch_id;
          STATE.columns = payload.columns || [];
          STATE.filename = payload.filename;
          STATE.mapping = payload.suggested_mapping || {};
          if (payload.app_fields) STATE.appFields = payload.app_fields;
          var title = qs(document, "#preview-title");
          if (title) title.textContent = payload.filename + " — " + CL.fmtNumber(payload.total_rows, 0) + " ligne(s) détectée(s)";
          var warnings = qs(document, "#preview-warnings");
          if (warnings) {
            warnings.innerHTML = "";
            (payload.warnings || []).forEach(function (message) {
              var node = document.createElement("div");
              node.className = "notice notice--attention";
              node.textContent = message;
              warnings.appendChild(node);
            });
            warnings.hidden = !(payload.warnings || []).length;
          }
          renderPreviewTable(qs(document, "#preview-table"), payload.preview || []);
          setStep(2);
        }).catch(function (error) {
          CL.flash("danger", error.message);
        }).finally(function () {
          CL.setBusy(uploadButton, false);
        });
      });
    }

    var toMapping = qs(document, "#to-mapping");
    if (toMapping) {
      toMapping.addEventListener("click", function (event) {
        event.preventDefault();
        buildMappingRows();
        setStep(3);
      });
    }

    var backToPreview = qs(document, "#back-to-preview");
    if (backToPreview) backToPreview.addEventListener("click", function (event) { event.preventDefault(); setStep(2); });

    var validateButton = qs(document, "#validate-button");
    if (validateButton) {
      validateButton.addEventListener("click", function (event) {
        event.preventDefault();
        var mapping = collectMapping();
        if (!mapping.date) { CL.flash("danger", "Associez la colonne « Date » avant de vérifier."); return; }
        var duplicates = qs(document, "#include-duplicates");
        CL.setBusy(validateButton, true);
        CL.postJSON("/api/imports/" + STATE.batchId + "/mapping", {
          mapping: mapping,
          include_duplicates: !!(duplicates && duplicates.checked),
        }).then(function (payload) {
          renderStats(payload.stats);
          renderIssues(payload.issues);
          renderValidationPreview(payload.preview);
          var errorsLink = qs(document, "#errors-link");
          if (errorsLink) errorsLink.href = "/api/imports/" + STATE.batchId + "/errors.csv";
          setStep(4);
        }).catch(function (error) {
          CL.flash("danger", error.message);
        }).finally(function () {
          CL.setBusy(validateButton, false);
        });
      });
    }

    var duplicates = qs(document, "#include-duplicates");
    if (duplicates) {
      duplicates.addEventListener("change", function () {
        var button = qs(document, "#validate-button");
        if (button) button.click();
      });
    }

    var backToMapping = qs(document, "#back-to-mapping");
    if (backToMapping) backToMapping.addEventListener("click", function (event) { event.preventDefault(); setStep(3); });

    var confirmButton = qs(document, "#confirm-button");
    if (confirmButton) {
      confirmButton.addEventListener("click", function (event) {
        event.preventDefault();
        var duplicatesBox = qs(document, "#include-duplicates");
        CL.setBusy(confirmButton, true);
        CL.postJSON("/api/imports/" + STATE.batchId + "/confirm", {
          mapping: collectMapping(),
          include_duplicates: !!(duplicatesBox && duplicatesBox.checked),
        }).then(function (payload) {
          var summary = qs(document, "#confirm-summary");
          if (summary) {
            summary.hidden = false;
            summary.textContent = "Importation terminée : " + payload.created + " dépense(s) créée(s), " +
              payload.carbon_created + " estimation(s) carbone associée(s).";
          }
          window.setTimeout(function () { window.location.href = "/expenses?period=tout"; }, 1200);
        }).catch(function (error) {
          CL.flash("danger", error.message);
          CL.setBusy(confirmButton, false);
        });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
