/* Tradewind - lightweight progressive enhancement.
   Every feature here has a working non-JavaScript fallback (normal form posts). */
(function () {
  "use strict";

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function csrfToken() {
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    return field ? field.value : getCookie("csrftoken");
  }

  function showToast(message, kind) {
    var zone = document.getElementById("toast-zone");
    if (!zone) { return; }
    var el = document.createElement("div");
    el.className = "alert alert-" + (kind || "success") + " shadow mb-0";
    el.setAttribute("role", "status");
    el.textContent = message;
    zone.appendChild(el);
    window.setTimeout(function () { el.remove(); }, 4000);
  }

  function setBadge(id, count) {
    var badge = document.getElementById(id);
    if (!badge) { return; }
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.setAttribute("data-count", String(count));
    badge.classList.add("pulse");
    window.setTimeout(function () { badge.classList.remove("pulse"); }, 220);
  }

  /* ---- Wishlist heart (AJAX, falls back to a normal POST) ---------------- */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("form[data-wishlist-form]")) { return; }
    event.preventDefault();
    var button = form.querySelector("button");
    if (button) { button.disabled = true; }
    fetch(form.action, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
    })
      .then(function (response) {
        if (response.redirected && /\/accounts\/login\//.test(response.url)) {
          window.location.href = response.url;
          return null;
        }
        if (!response.ok) { throw new Error("status " + response.status); }
        return response.json();
      })
      .then(function (data) {
        if (!data) { return; }
        if (button) {
          button.classList.toggle("is-saved", data.saved);
          button.setAttribute("aria-pressed", data.saved ? "true" : "false");
          var icon = button.querySelector("i");
          if (icon) { icon.className = data.saved ? "bi bi-heart-fill" : "bi bi-heart"; }
          button.classList.remove("pop");
          void button.offsetWidth; /* restart the animation */
          button.classList.add("pop");
        }
        showToast(data.message, "success");
      })
      .catch(function () {
        showToast("Sorry, that did not work. Please try again.", "danger");
      })
      .then(function () {
        if (button) { button.disabled = false; }
      });
  });

  /* ---- Loading state on submit buttons ----------------------------------- */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !form.matches || !form.matches("form")) { return; }
    var button = event.submitter || form.querySelector("button[type=submit]");
    if (!button || button.hasAttribute("data-no-loading")) { return; }
    window.setTimeout(function () {
      if (button.disabled) { return; }
      button.classList.add("btn-loading");
      button.setAttribute("aria-busy", "true");
      var spinner = document.createElement("span");
      spinner.className = "spinner-border spinner-border-sm";
      spinner.setAttribute("aria-hidden", "true");
      button.insertBefore(spinner, button.firstChild);
      button.disabled = true;
    }, 0);
  });
  /* Restore buttons when the page is shown again from the back/forward cache. */
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) { return; }
    document.querySelectorAll(".btn-loading").forEach(function (button) {
      button.classList.remove("btn-loading");
      button.disabled = false;
      var spinner = button.querySelector(".spinner-border");
      if (spinner) { spinner.remove(); }
    });
  });

  /* ---- Confirmation dialog for destructive actions ------------------------ */
  var pendingForm = null;
  var confirmModalEl = document.getElementById("confirmModal");
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("form[data-confirm]")) { return; }
    if (form.dataset.confirmed === "1") { return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!confirmModalEl || !window.bootstrap) {
      /* Without the modal, fall back to the browser's own confirm box. */
      if (window.confirm(form.getAttribute("data-confirm"))) {
        form.dataset.confirmed = "1";
        form.submit();
      }
      return;
    }
    pendingForm = form;
    confirmModalEl.querySelector("[data-confirm-message]").textContent = form.getAttribute("data-confirm");
    window.bootstrap.Modal.getOrCreateInstance(confirmModalEl).show();
  }, true);
  if (confirmModalEl) {
    confirmModalEl.querySelector("[data-confirm-accept]").addEventListener("click", function () {
      if (pendingForm) {
        pendingForm.dataset.confirmed = "1";
        pendingForm.submit();
      }
    });
  }

  /* ---- Product gallery thumbnails ----------------------------------------- */
  document.querySelectorAll("[data-gallery-thumb]").forEach(function (thumb) {
    thumb.addEventListener("click", function () {
      var main = document.getElementById("gallery-main-img");
      if (!main) { return; }
      main.src = thumb.getAttribute("data-full");
      document.querySelectorAll("[data-gallery-thumb]").forEach(function (t) { t.classList.remove("active"); });
      thumb.classList.add("active");
    });
  });

  /* ---- Notification badge refresh ------------------------------------------ */
  var badge = document.getElementById("notif-badge");
  if (badge && badge.dataset.url) {
    window.setInterval(function () {
      if (document.hidden) { return; }
      fetch(badge.dataset.url, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (data && String(data.count) !== badge.getAttribute("data-count")) {
            setBadge("notif-badge", data.count);
          }
        })
        .catch(function () { /* the badge simply stays as it is */ });
    }, 60000);
  }

  /* ---- Auto-dismiss success alerts ------------------------------------------ */
  document.querySelectorAll(".alert[data-autodismiss]").forEach(function (alertEl) {
    window.setTimeout(function () {
      if (window.bootstrap) {
        window.bootstrap.Alert.getOrCreateInstance(alertEl).close();
      } else {
        alertEl.remove();
      }
    }, 6000);
  });
})();
