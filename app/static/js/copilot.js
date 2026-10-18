/* CarbonLedger AI — assistant : envoi de questions, rendu des réponses (mode IA ou démonstration). */
(function () {
  "use strict";

  var CL = window.CL;
  var HISTORY = [];

  function qs(root, selector) { return root.querySelector(selector); }
  function qsa(root, selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderMarkdown(text) {
    var lines = String(text || "").split("\n");
    var parts = [];
    var inList = false;
    lines.forEach(function (rawLine) {
      var line = rawLine.trim();
      if (!line) {
        if (inList) { parts.push("</ul>"); inList = false; }
        return;
      }
      var escaped = escapeHtml(line).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      if (line.charAt(0) === "•") {
        if (!inList) { parts.push('<ul class="copilot-list">'); inList = true; }
        parts.push("<li>" + escaped.replace(/^•\s*/, "") + "</li>");
      } else {
        if (inList) { parts.push("</ul>"); inList = false; }
        if (line.charAt(0) === "→") parts.push('<p class="copilot-note">' + escaped.replace(/^→\s*/, "") + "</p>");
        else parts.push("<p>" + escaped + "</p>");
      }
    });
    if (inList) parts.push("</ul>");
    return parts.join("");
  }

  function addMessage(role, bodyHtml, meta) {
    var container = qs(document, "#chat-messages");
    if (!container) return null;
    var node = document.createElement("div");
    node.className = "msg msg--" + role;
    if (meta) {
      var metaNode = document.createElement("div");
      metaNode.className = "msg__meta";
      metaNode.textContent = meta;
      node.appendChild(metaNode);
    }
    var body = document.createElement("div");
    body.className = "msg__body";
    body.innerHTML = bodyHtml;
    node.appendChild(body);
    container.appendChild(node);
    container.scrollTop = container.scrollHeight;
    return node;
  }

  function ask(question) {
    if (!question) return;
    var input = qs(document, "#copilot-question");
    var button = qs(document, "#copilot-send");
    addMessage("user", "<p>" + escapeHtml(question) + "</p>", null);
    if (input) input.value = "";
    CL.setBusy(button, true);
    var pending = addMessage("assistant", '<p class="muted">Analyse des données enregistrées…</p>', "CarbonLedger Copilot");

    CL.postJSON("/api/copilot/ask", { question: question, history: HISTORY.slice(-6) }).then(function (payload) {
      var meta = payload.mode === "ia"
        ? "Réponse IA (modèle externe, à partir du contexte calculé)"
        : "Mode démonstration (règles déterministes, aucune IA externe)";
      pending.remove();
      var html = renderMarkdown(payload.answer);
      if (payload.error) {
        html += '<div class="notice notice--attention"><strong class="notice__title">' + escapeHtml(payload.error) + "</strong></div>";
      }
      if (payload.data_used && payload.data_used.length) {
        html += '<p class="disclaimers">Données utilisées : ' + escapeHtml(payload.data_used.join(" ; ")) + ".</p>";
      }
      (payload.disclaimers || []).forEach(function (line) {
        html += '<p class="disclaimers">' + escapeHtml(line) + "</p>";
      });
      addMessage("assistant", html, meta);
      HISTORY.push({ role: "user", content: question });
      HISTORY.push({ role: "assistant", content: payload.answer });
    }).catch(function (error) {
      pending.remove();
      addMessage("assistant", '<div class="notice notice--danger"><strong class="notice__title">Erreur</strong><span class="notice__message">' +
        escapeHtml(error.message) + "</span></div>", "CarbonLedger Copilot");
    }).finally(function () {
      CL.setBusy(button, false);
    });
  }

  function init() {
    var page = qs(document, "#copilot-page");
    if (!page) return;
    var form = qs(document, "#copilot-form");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var input = qs(document, "#copilot-question");
        ask(input ? input.value.trim() : "");
      });
    }
    qsa(document, "[data-question]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var question = chip.getAttribute("data-question");
        var input = qs(document, "#copilot-question");
        if (input) input.value = question;
        ask(question);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
