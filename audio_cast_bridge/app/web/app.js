const $ = (id) => document.getElementById(id);

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

function renderList(eligible, skipped) {
  const el = $("eligible");
  if (!eligible.length) {
    el.innerHTML = '<p class="hint">No eligible LinkPlay/DLNA media_player entities found.</p>';
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
    input.addEventListener("change", renderSizing);
  });
  renderSizing();
}

async function loadDevices() {
  const res = await fetch("api/devices");
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  renderList(data.eligible || [], data.skipped || []);
  const cfg = data.config || {};
  const pending = cfg.pending || cfg.committed || {};
  if (pending.max_concurrent_streams) {
    $("max_streams").value = pending.max_concurrent_streams;
  }
  $("restart-banner").classList.toggle("hidden", !cfg.needs_restart);
  const committedCount = ((cfg.committed && cfg.committed.selected_entities) || []).length;
  $("version").textContent =
    "Add-on v" + (cfg.addon_version || "?") + " · committed " + committedCount + " bridge(s)";
  renderSizing();
}

async function loadHealth() {
  const res = await fetch("api/health");
  const data = await res.json();
  $("health").textContent = JSON.stringify(data, null, 2);
}

async function saveConfig() {
  $("message").textContent = "";
  $("message").classList.remove("error");
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
    $("message").textContent = data.error || "Save failed";
    $("message").classList.add("error");
    return;
  }
  $("message").textContent = data.message || "Saved";
  $("restart-banner").classList.remove("hidden");
  await loadDevices();
  await loadHealth();
}

$("max_streams").addEventListener("input", renderSizing);
$("save").addEventListener("click", function () {
  saveConfig().catch(function (err) {
    $("message").textContent = String(err);
    $("message").classList.add("error");
  });
});
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
