const $ = (id) => document.getElementById(id);

let applyTimer = null;
let applying = false;
let suppressChange = false;

function estimateRam(n, streams) {
  return 128 + n * 12 + streams * 48;
}

function recommendFree(suggested) {
  const steps = [256, 384, 512, 768, 1024, 1536, 2048];
  for (const s of steps) if (suggested <= s) return s;
  return Math.ceil(suggested / 256) * 256;
}

function selectedIds() {
  return [...document.querySelectorAll('input[name="entity"]:checked')].map((el) => el.value);
}

function renderSizing() {
  const n = selectedIds().length;
  const streams = Number($("max_streams").value || 2);
  const suggested = estimateRam(n, streams);
  const free = recommendFree(suggested);
  $("sizing").innerHTML =
    "<div><strong>" + n + "</strong> selected · <strong>" + streams + "</strong> max streams</div>" +
    "<div>Suggested RAM ≈ <strong>" + suggested + " MB</strong></div>" +
    "<div>Recommend ~<strong>" + free + " MB</strong> free on the host</div>";
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function scheduleApply() {
  if (suppressChange || applying) return;
  renderSizing();
  if (applyTimer) clearTimeout(applyTimer);
  applyTimer = setTimeout(function () {
    applySelection().catch(function (err) {
      $("message").textContent = String(err);
      $("message").classList.add("error");
      applying = false;
      $("restart-banner").classList.add("hidden");
    });
  }, 600);
}

function renderList(eligible, skipped) {
  const el = $("eligible");
  if (!eligible.length) {
    el.innerHTML = '<p class="hint">No eligible speakers found. Looking for wiim / linkplay / dlna_dmr. See platform counts below.</p>';
  } else {
    el.innerHTML = eligible.map(function (d) {
      return (
        '<div class="item"><label>' +
        '<input type="checkbox" name="entity" value="' + escapeHtml(d.entity_id) + '"' +
        (d.selected ? " checked" : "") + " />" +
        "<span><div class=\"name\">" + escapeHtml(d.friendly_name) +
        ' <span class="badge">' + escapeHtml(d.domain) + "</span>" +
        ' <span class="badge">' + escapeHtml(d.state || "") + "</span></div>" +
        '<div class="id">' + escapeHtml(d.entity_id) + " → " + escapeHtml(d.cast_name) +
        "</div></span></label></div>"
      );
    }).join("");
  }
  const sk = $("skipped");
  if (!skipped.length) {
    sk.innerHTML = '<p class="hint">None</p>';
  } else {
    sk.innerHTML = skipped.map(function (d) {
      return (
        '<div class="item"><span><div class="name">' + escapeHtml(d.friendly_name) +
        ' <span class="badge">' + escapeHtml(d.skip_reason || "skipped") + "</span></div>" +
        '<div class="id">' + escapeHtml(d.entity_id) + "</div></span></div>"
      );
    }).join("");
  }
  el.querySelectorAll('input[name="entity"]').forEach(function (input) {
    input.addEventListener("change", scheduleApply);
  });
  renderSizing();
}

async function loadDevices() {
  const res = await fetch("api/devices");
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  suppressChange = true;
  renderList(data.eligible || [], data.skipped || []);
  const diag = data.diagnostics || {};
  const tracked = diag.tracked_platforms || {};
  const all = diag.all_platforms || {};
  const allParts = Object.keys(all).map(function (k) { return k + "=" + all[k]; }).join(", ");
  $("diag").textContent =
    "HA media_players: " + (diag.media_player_total ?? "?") +
    " · wiim: " + (tracked.wiim ?? 0) +
    " · linkplay: " + (tracked.linkplay ?? 0) +
    " · dlna_dmr: " + (tracked.dlna_dmr ?? 0) +
    " · cast: " + (tracked.cast ?? 0) +
    (allParts ? " · platforms: " + allParts : "");
  const cfg = ((data.config || {}).config) || {};
  if (cfg.max_concurrent_streams) {
    $("max_streams").value = cfg.max_concurrent_streams;
  }
  renderSizing();
  suppressChange = false;
}

async function loadHealth() {
  const res = await fetch("api/health");
  const data = await res.json();
  $("health").textContent = JSON.stringify(data, null, 2);
}

async function applySelection() {
  if (applying) return;
  applying = true;
  $("message").textContent = "";
  $("message").classList.remove("error");
  $("restart-banner").classList.remove("hidden");
  const body = {
    selected_entities: selectedIds(),
    max_concurrent_streams: Number($("max_streams").value || 2),
  };
  const res = await fetch("api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    applying = false;
    $("restart-banner").classList.add("hidden");
    $("message").textContent = data.error || "Apply failed";
    $("message").classList.add("error");
    return;
  }
  $("message").textContent = data.message || "Restarting…";
  // UI will drop while the add-on restarts; poll until it returns
  setTimeout(function poll() {
    fetch("api/health")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function () {
        applying = false;
        $("restart-banner").classList.add("hidden");
        $("message").textContent = "Applied.";
        return Promise.all([loadDevices(), loadHealth()]);
      })
      .catch(function () { setTimeout(poll, 1500); });
  }, 2000);
}

$("max_streams").addEventListener("change", scheduleApply);
$("reload").addEventListener("click", function () {
  Promise.all([loadDevices(), loadHealth()]).catch(function (err) {
    $("message").textContent = String(err);
    $("message").classList.add("error");
  });
});

Promise.all([loadDevices(), loadHealth()]).catch(function (err) {
  $("message").textContent = String(err);
  $("message").classList.add("error");
});
