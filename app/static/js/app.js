/* CarbonLedger AI — utilitaires partagés (aucune dépendance externe, CSP 'self'). */
(function () {
  "use strict";

  var NBSP = "\u202f";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function toNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "number") return value;
    var text = String(value).trim().replace(/\u202f/g, "").replace(/\u00a0/g, "").replace(/\s/g, "");
    if (text.indexOf(",") !== -1 && text.indexOf(".") !== -1) {
      text = text.lastIndexOf(",") > text.lastIndexOf(".")
        ? text.replace(/\./g, "").replace(",", ".")
        : text.replace(/,/g, "");
    } else if (text.indexOf(",") !== -1) {
      text = text.replace(",", ".");
    }
    var parsed = parseFloat(text);
    return isNaN(parsed) ? null : parsed;
  }

  function group(value, decimals) {
    var fixed = Number(value).toFixed(decimals);
    var parts = fixed.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
    return parts.join(",");
  }

  function fmtMoney(value, decimals) {
    var number = toNumber(value);
    if (number === null) return "—";
    var d = decimals === undefined || decimals === null ? 2 : decimals;
    return group(number, d) + NBSP + "DH";
  }

  function fmtNumber(value, decimals) {
    var number = toNumber(value);
    if (number === null) return "—";
    var d = decimals === undefined || decimals === null ? 2 : decimals;
    return group(number, d);
  }

  function fmtTco2e(value) {
    var number = toNumber(value);
    if (number === null) return "—";
    return group(number, 2) + NBSP + "t CO₂e";
  }

  function getJSON(url) {
    return fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok || payload.ok === false) {
          throw new Error(payload.error || "Erreur " + response.status);
        }
        return payload;
      });
    });
  }

  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(payload || {}),
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || "Erreur " + response.status);
        }
        return data;
      });
    });
  }

  function postForm(url, formData) {
    if (formData instanceof FormData && !formData.has("csrf_token")) {
      formData.append("csrf_token", csrfToken());
    }
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfToken() },
      body: formData,
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || "Erreur " + response.status);
        }
        return data;
      });
    });
  }

  function flash(level, message) {
    var container = document.querySelector(".flashes");
    if (!container) {
      container = document.createElement("div");
      container.className = "flashes";
      container.setAttribute("role", "status");
      var content = document.querySelector(".content") || document.querySelector(".guest-card");
      if (content) content.insertBefore(container, content.firstChild);
    }
    var node = document.createElement("div");
    node.className = "flash flash--" + (level || "info");
    var text = document.createElement("span");
    text.className = "flash__text";
    text.textContent = message;
    var close = document.createElement("button");
    close.type = "button";
    close.className = "flash__close";
    close.setAttribute("aria-label", "Fermer");
    close.textContent = "×";
    close.addEventListener("click", function () { node.remove(); });
    node.appendChild(text);
    node.appendChild(close);
    container.appendChild(node);
    node.scrollIntoView({ block: "nearest" });
    return node;
  }

  function setBusy(button, busy) {
    if (!button) return;
    if (busy) {
      button.setAttribute("aria-busy", "true");
      button.setAttribute("disabled", "disabled");
    } else {
      button.removeAttribute("aria-busy");
      button.removeAttribute("disabled");
    }
  }

  function init() {
    // Fermer les menus déroulants au clic extérieur.
    document.addEventListener("click", function (event) {
      document.querySelectorAll("details.dropdown[open]").forEach(function (details) {
        if (!details.contains(event.target)) details.removeAttribute("open");
      });
    });

    // Confirmations explicites (données supprimées).
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        var message = form.getAttribute("data-confirm") || "Confirmer cette action ?";
        if (!window.confirm(message)) event.preventDefault();
      });
    });
    document.querySelectorAll("[data-confirm-click]").forEach(function (node) {
      node.addEventListener("click", function (event) {
        if (!window.confirm(node.getAttribute("data-confirm-click"))) event.preventDefault();
      });
    });

    // Fermeture des messages flash.
    document.querySelectorAll("[data-dismiss], .flash").forEach(function (flashNode) {
      var button = flashNode.querySelector ? flashNode.querySelector("[data-dismiss]") : null;
      if (button) {
        button.addEventListener("click", function () { flashNode.remove(); });
      }
    });
    window.setTimeout(function () {
      document.querySelectorAll(".flash--success, .flash--info").forEach(function (node) { node.remove(); });
    }, 11000);
  }

  window.CL = {
    csrfToken: csrfToken,
    toNumber: toNumber,
    fmtMoney: fmtMoney,
    fmtNumber: fmtNumber,
    fmtTco2e: fmtTco2e,
    getJSON: getJSON,
    postJSON: postJSON,
    postForm: postForm,
    flash: flash,
    setBusy: setBusy,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
