/*
 * NSPBX — widget embebible "hablar con un agente".
 *
 * Uso en cualquier sitio web:
 *   <script src="https://TU-PBX/webcall.js" data-host="https://TU-PBX" data-empresa="SU-EMPRESA" async></script>
 *
 * El snippet exacto (con su data-empresa) está en Ajustes del panel.
 *
 * Atributos opcionales del <script>:
 *   data-empresa   identificador de la empresa dueña de la burbuja. Sin él
 *                  es la empresa inicial de la plataforma (snippets viejos).
 *   data-host      URL base del PBX que sirve /webcall.js y la página /webcall
 *                  (por defecto: el origen de este script)
 *   data-api       URL base de la API /api/webcall/* (por defecto: data-host).
 *                  Solo hace falta si el panel y el backend están en orígenes
 *                  distintos (p. ej. en desarrollo local: :3005 y :8001).
 *   data-position  "right" (def.) | "left"
 *   data-color     color del botón (por defecto: #2563eb)
 *   data-label     texto junto al icono (por defecto: "Llamar a un agente")
 *
 * No hace nada si el widget está desactivado en Ajustes del PBX.
 */
(function () {
  "use strict";
  if (window.__nspbxWebcallLoaded) return;
  window.__nspbxWebcallLoaded = true;

  // document.currentScript es null si el <script> se cargó async/diferido
  // (p. ej. via next/script) — se cae a buscar la etiqueta por su src.
  var script =
    document.currentScript ||
    document.querySelector('script[src*="webcall.js"]');
  function attr(name, def) {
    var v = script && script.getAttribute(name);
    return v == null || v === "" ? def : v;
  }

  var host = attr("data-host", "");
  if (!host && script) {
    try {
      host = new URL(script.src).origin;
    } catch {
      host = "";
    }
  }
  if (!host) return; // sin host no hay a dónde llamar
  host = host.replace(/\/+$/, "");
  var apiBase = (attr("data-api", "") || host).replace(/\/+$/, "");
  var side = attr("data-position", "right") === "left" ? "left" : "right";
  var color = attr("data-color", "#2563eb");
  var label = attr("data-label", "Llamar a un agente");
  var empresa = attr("data-empresa", "");
  var qEmpresa = empresa ? "?empresa=" + encodeURIComponent(empresa) : "";

  fetch(apiBase + "/api/webcall/config" + qEmpresa, { mode: "cors" })
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      if (!cfg || !cfg.enabled) return;
      build();
    })
    .catch(function () { /* PBX inalcanzable: no se dibuja nada */ });

  function build() {
    var style = document.createElement("style");
    style.textContent = [
      ".nspbx-wc-btn{position:fixed;bottom:20px;" + side + ":20px;z-index:2147483000;",
      "display:flex;align-items:center;gap:10px;border:0;cursor:pointer;border-radius:9999px;",
      "padding:14px 20px;font:600 14px/1 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;",
      "color:#fff;background:" + color + ";box-shadow:0 8px 24px rgba(0,0,0,.25);",
      "transition:transform .15s ease}",
      ".nspbx-wc-btn:hover{transform:translateY(-2px)}",
      ".nspbx-wc-btn.calling{animation:nspbx-wc-pulse 1.4s ease-in-out infinite}",
      "@keyframes nspbx-wc-pulse{0%,100%{box-shadow:0 8px 24px rgba(0,0,0,.25)}50%{box-shadow:0 0 0 10px rgba(37,99,235,.25)}}",
      ".nspbx-wc-btn svg{width:20px;height:20px;flex:none}",
      ".nspbx-wc-panel{position:fixed;bottom:92px;" + side + ":20px;z-index:2147483000;",
      "width:360px;max-width:calc(100vw - 40px);height:540px;max-height:calc(100vh - 120px);",
      "border:0;border-radius:20px;overflow:hidden;background:#fff;",
      "box-shadow:0 16px 48px rgba(0,0,0,.32);display:none}",
      ".nspbx-wc-panel.open{display:block}",
      "@media(max-width:480px){.nspbx-wc-panel{width:calc(100vw - 24px);" + side + ":12px;height:calc(100vh - 96px);bottom:84px}}",
    ].join("");
    document.head.appendChild(style);

    var btn = document.createElement("button");
    btn.className = "nspbx-wc-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", label);
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<path stroke-linecap="round" stroke-linejoin="round" d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"/></svg>' +
      "<span>" + escapeHtml(label) + "</span>";

    var panel = document.createElement("iframe");
    panel.className = "nspbx-wc-panel";
    panel.setAttribute("allow", "microphone; autoplay");
    panel.title = label;

    var loaded = false;
    function toggle() {
      var opening = !panel.classList.contains("open");
      if (opening && !loaded) {
        var q = [];
        if (apiBase !== host) q.push("api=" + encodeURIComponent(apiBase));
        if (empresa) q.push("empresa=" + encodeURIComponent(empresa));
        panel.src = host + "/webcall" + (q.length ? "?" + q.join("&") : "");
        loaded = true;
      }
      panel.classList.toggle("open", opening);
    }
    btn.addEventListener("click", toggle);

    window.addEventListener("message", function (ev) {
      var d = ev.data;
      if (!d || d.source !== "nspbx-webcall") return;
      if (d.action === "close") panel.classList.remove("open");
      if (d.phase) btn.classList.toggle("calling", d.phase === "in-call" || d.phase === "queued");
    });

    document.body.appendChild(btn);
    document.body.appendChild(panel);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
})();
