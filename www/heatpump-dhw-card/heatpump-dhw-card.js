/**
 * Heat Pump DHW Card — v2.16
 *
 * Configuratie:
 *   type: custom:heatpump-dhw-card
 *   title: Warmtepomp Boiler           # optioneel
 *   temp_sensor: sensor.dhw_boiler_temp
 *   mode_sensor: sensor.dhw_active_mode
 *   status_sensor: sensor.dhw_status_text
 *   power_sensor: sensor.dhw_power_w          # optioneel
 *   session_kwh_sensor: sensor.dhw_session_kwh
 *   session_cost_sensor: sensor.dhw_session_cost
 *   next_heating_sensor: sensor.dhw_next_heating
 *   price_forecast_sensor: sensor.dynamic_electricity_price  # voor prijsgrafiek
 *   target_temp_sensor: number.boiler_setpoint  # optioneel, doeltemperatuur
 *   cheap_hours: 2                      # optioneel, goedkoopste blokken markeren in grafiek
 *   solar_switch: switch.dhw_solar_mode
 *   price_switch: switch.dhw_price_mode
 *   boost_switch: switch.dhw_boost_mode
 *   vacation_switch: switch.dhw_vacation_mode
 *   legionella_switch: switch.dhw_legionella_mode
 *   manual_switch: switch.dhw_manual_mode   # grote aan/uit knop bovenaan
 */

const MODE_COLORS = {
  solar:      "#f59e0b",
  boost:      "#f97316",
  schedule:   "#3b82f6",
  legionella: "#ef4444",
  vacation:   "#a78bfa",
  idle:       "#6b7280",
  manual:     "#8b5cf6",
  anti_block: "#64748b",
};

const MODE_LABELS = {
  solar:      "Zonne-energie",
  boost:      "Boost",
  schedule:   "Douche schema",
  legionella: "Legionella run",
  vacation:   "Vakantie",
  idle:       "Standby",
  manual:     "Handmatig",
  anti_block: "Anti-blokkeer",
};

const HEATING_MODES = new Set(["solar", "boost", "schedule", "legionella", "manual", "anti_block"]);

class HeatpumpDhwCard extends HTMLElement {
  setConfig(config) {
    if (!config.temp_sensor) throw new Error("temp_sensor is vereist");
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() { return 6; }

  _state(id) {
    if (!id || !this._hass) return null;
    const s = this._hass.states[id];
    return s ? s.state : null;
  }

  _fmt(val, dec = 1, fallback = "—") {
    if (val == null || val === "unknown" || val === "unavailable") return fallback;
    const n = parseFloat(val);
    return isNaN(n) ? fallback : n.toFixed(dec);
  }

  _tempColor(t) {
    if (isNaN(t)) return "#6b7280";
    if (t < 35)   return "#3b82f6";
    if (t < 45)   return "#22c55e";
    if (t < 55)   return "#f59e0b";
    return "#ef4444";
  }

  _formatRelTime(isoStr) {
    if (!isoStr || isoStr === "unknown" || isoStr === "unavailable") return null;
    const d = new Date(isoStr);
    if (isNaN(d)) return null;
    const diffMin = Math.round((d - Date.now()) / 60000);
    if (diffMin <= 0) return "Nu";
    if (diffMin < 60) return `over ${diffMin} min`;
    const h = Math.floor(diffMin / 60), m = diffMin % 60;
    const t = d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
    return `${t} (over ${h}u${m ? m + "m" : ""})`;
  }

  _extractTargetTemp(statusText) {
    if (!statusText) return null;
    const m = statusText.match(/→\s*(\d+(?:\.\d+)?)\s*°C/);
    return m ? parseFloat(m[1]) : null;
  }

  async _toggleSwitch(id) {
    if (!id || !this._hass) return;
    const svc = this._state(id) === "on" ? "turn_off" : "turn_on";
    await this._hass.callService("switch", svc, { entity_id: id });
  }

  // ── Price forecast parser (handles Zonneplan, Nordpool, Tibber, generic) ──
  _parseForecast(entityId) {
    if (!entityId || !this._hass) return [];
    const state = this._hass.states[entityId];
    if (!state) return [];
    const attrs = state.attributes;

    const tryList = (v) => {
      if (!v) return [];
      if (typeof v === "string") { try { v = JSON.parse(v); } catch { return []; } }
      return Array.isArray(v) ? v : [];
    };

    let entries = [];

    // Zonneplan app: forecast [{datetime, electricity_price}]
    const zp = tryList(attrs.forecast);
    if (zp.length && zp[0]?.electricity_price !== undefined) {
      entries = zp.filter(e => e.datetime).map(e => ({
        start: new Date(e.datetime),
        price: parseFloat(e.electricity_price) / 1e6,
      }));
    }

    // Zonneplan template: prices_today/prices_tomorrow [{time, price}]
    if (!entries.length) {
      for (const k of ["prices_today", "prices_tomorrow"])
        for (const e of tryList(attrs[k]))
          if (e.time != null && e.price != null)
            entries.push({ start: new Date(e.time), price: parseFloat(e.price) });
    }

    // Nordpool / ENTSOE: raw_today/raw_tomorrow [{start, value}]
    if (!entries.length) {
      for (const k of ["raw_today", "raw_tomorrow"])
        for (const e of tryList(attrs[k]))
          if (e.start != null && e.value != null)
            entries.push({ start: new Date(e.start), price: parseFloat(e.value) });
    }

    // Tibber: prices/price_info/today/tomorrow [{startsAt, total}]
    if (!entries.length) {
      for (const k of ["prices", "price_info", "today", "tomorrow"]) {
        const list = tryList(attrs[k]).filter(e => e.startsAt && e.total != null);
        if (list.length) { entries = list.map(e => ({ start: new Date(e.startsAt), price: e.total })); break; }
      }
    }

    // Generic fallback: scan list attributes for time/price field pairs
    if (!entries.length) {
      const TK = ["start", "time", "datetime", "startsAt", "hour", "timestamp", "start_time"];
      const PK = ["price", "value", "total", "amount", "electricity_price", "price_ct"];
      for (const [, val] of Object.entries(attrs)) {
        const list = tryList(val);
        if (!list.length || typeof list[0] !== "object") continue;
        const tk = TK.find(k => k in list[0]);
        const pk = PK.find(k => k in list[0]);
        if (!tk || !pk) continue;
        const mult = pk === "electricity_price" ? 1e-6 : pk === "price_ct" ? 0.01 : 1;
        entries = list.filter(e => e[tk] != null && e[pk] != null).map(e => ({
          start: new Date(e[tk]),
          price: parseFloat(e[pk]) * mult,
        }));
        break;
      }
    }

    entries = entries.filter(e => !isNaN(e.start) && isFinite(e.price));

    // Auto-scale: electricity prices should be < 2 €/kWh; if median is higher the unit is wrong
    if (entries.length) {
      const sorted = entries.slice().sort((a, b) => a.price - b.price);
      const median = sorted[Math.floor(sorted.length / 2)].price;
      let scale = 1;
      while (median / scale > 2) scale *= 10;
      if (scale > 1) entries = entries.map(e => ({ ...e, price: e.price / scale }));
    }

    return entries.sort((a, b) => a.start - b.start);
  }

  // ── Price chart renderer ──
  _renderPriceChart(allPrices, plannedHeatingSlots) {
    if (!allPrices.length) return "";

    // Detect slot resolution
    let slotMin = 60;
    if (allPrices.length >= 2) {
      const delta = Math.round((allPrices[1].start - allPrices[0].start) / 60000);
      if ([15, 30, 60].includes(delta)) slotMin = delta;
    }
    const slotMs = slotMin * 60000;

    // Current slot
    const now = Date.now();
    const curSlotMs = Math.floor(now / slotMs) * slotMs;

    // Show 24 bars from current slot (window in hours depends on slot size)
    const bars = allPrices
      .filter(e => e.start.getTime() >= curSlotMs)
      .slice(0, 24);

    if (!bars.length) return "";

    const prices = bars.map(e => e.price);
    const minP = Math.min(...prices);
    const maxP = Math.max(...prices);
    const range = maxP - minP || 0.001;

    // Planned heating slots from integration (via next_heating sensor attribute)
    const plannedSlots = new Set(
      (plannedHeatingSlots || []).map(iso => {
        const d = new Date(iso);
        return Math.floor(d.getTime() / slotMs) * slotMs;
      })
    );

    // Color: green (cheap) → amber (mid) → red (expensive)
    const priceColor = (p) => {
      const t = (p - minP) / range;
      if (t < 0.5) {
        const tt = t * 2;
        return `rgb(${Math.round(34 + 211 * tt)},${Math.round(197 - 39 * tt)},${Math.round(94 - 83 * tt)})`;
      }
      const tt = (t - 0.5) * 2;
      return `rgb(${Math.round(245 - 6 * tt)},${Math.round(158 - 90 * tt)},${Math.round(11 + 57 * tt)})`;
    };

    const labelEvery = slotMin === 15 ? 4 : slotMin === 30 ? 2 : 1;

    const barHtml = bars.map((entry, i) => {
      const ms = entry.start.getTime();
      const isCur   = ms === curSlotMs;
      const isCheap = plannedSlots.has(ms);

      const heightPct = (15 + ((entry.price - minP) / range) * 72).toFixed(1);
      const color = priceColor(entry.price);

      const showLabel = i % labelEvery === 0;
      const label = showLabel
        ? entry.start.toLocaleTimeString("nl-NL", {
            hour: "2-digit",
            minute: slotMin < 60 ? "2-digit" : undefined,
          })
        : "";

      const innerStyle = isCheap
        ? `background:rgba(255,255,255,0.45);border-radius:4px 4px 0 0;`
        : "";

      return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;min-width:0;">
        <div style="flex:1;display:flex;flex-direction:column;align-items:center;width:100%;${innerStyle}">
          <div style="flex:1;display:flex;align-items:flex-end;width:100%;padding:0 1px;">
            <div style="width:100%;height:${heightPct}%;background:${color};border-radius:2px 2px 0 0;"></div>
          </div>
        </div>
        <div style="font-size:8.5px;color:var(--secondary-text-color);text-align:center;margin-top:2px;overflow:hidden;white-space:nowrap;width:100%;">${label}</div>
      </div>`;
    }).join("");

    const hoursShown = (bars.length * slotMin / 60).toFixed(0);
    const fmt = p => `€${p.toFixed(3)}`;

    return `<div style="margin:14px 0 12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <span style="font-size:0.78rem;font-weight:500;color:var(--secondary-text-color);">Prijsgrafiek · ${hoursShown}u · ${slotMin}min</span>
        <span style="font-size:0.72rem;color:var(--secondary-text-color);">
          <span style="color:#22c55e;font-weight:700;">■</span>&thinsp;${fmt(minP)}
          &nbsp;–&nbsp;
          <span style="color:#ef4444;font-weight:700;">■</span>&thinsp;${fmt(maxP)}
        </span>
      </div>
      <div style="display:flex;height:90px;align-items:stretch;gap:1px;background:var(--secondary-background-color,#f3f4f6);border-radius:10px;padding:0 6px;overflow:hidden;">
        ${barHtml}
      </div>
    </div>`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const c = this._config;

    const temp       = this._state(c.temp_sensor);
    const rawMode    = this._state(c.mode_sensor) || "idle";
    const mode       = rawMode.replace(/-/g, "_");
    const status     = this._state(c.status_sensor) || "";
    const power      = this._state(c.power_sensor);
    const kwh        = this._state(c.session_kwh_sensor);
    const cost       = this._state(c.session_cost_sensor);
    const nextStr    = this._state(c.next_heating_sensor);

    const isHeating  = HEATING_MODES.has(mode);
    const modeColor  = MODE_COLORS[mode] || "#6b7280";
    const modeLabel  = MODE_LABELS[mode] || rawMode;
    const tempVal    = parseFloat(temp);
    const tempColor  = this._tempColor(tempVal);
    const title      = c.title || "Warmtepomp Boiler";
    const cheapHours = parseInt(c.cheap_hours) || 2;

    // Target temperature: dedicated sensor → parse from status text
    const targetRaw  = c.target_temp_sensor ? parseFloat(this._state(c.target_temp_sensor)) : NaN;
    const targetTemp = isFinite(targetRaw) ? targetRaw : this._extractTargetTemp(status);

    // Temperature bar (range 20–80 °C)
    const BAR_MIN = 20, BAR_MAX = 80, BAR_RANGE = BAR_MAX - BAR_MIN;
    const tempPct   = isNaN(tempVal) ? 0 : Math.max(0, Math.min(100, (tempVal - BAR_MIN) / BAR_RANGE * 100));
    const targetPct = targetTemp ? Math.max(0, Math.min(100, (targetTemp - BAR_MIN) / BAR_RANGE * 100)) : null;

    // Price chart
    const allPrices      = this._parseForecast(c.price_forecast_sensor);
    const nextHeatingDate = nextStr && nextStr !== "unknown" ? new Date(nextStr) : null;
    const nextHeatState  = c.next_heating_sensor ? this._hass.states[c.next_heating_sensor] : null;
    const plannedSlots   = nextHeatState?.attributes?.planned_heating_slots || [];
    // Derive expected duration from planned slots so it always matches the white bars shown
    let plannedMinutes = null;
    if (plannedSlots.length >= 2) {
      const slotMs = Math.abs(new Date(plannedSlots[1]) - new Date(plannedSlots[0]));
      plannedMinutes = Math.round(plannedSlots.length * slotMs / 60000);
    } else if (plannedSlots.length === 1) {
      plannedMinutes = 60;
    }
    const chartHtml      = c.price_forecast_sensor
      ? this._renderPriceChart(allPrices, plannedSlots)
      : "";

    const nextRel = this._formatRelTime(nextStr);

    // Mode switches (manual has its own big button below)
    const switches = [
      { id: c.solar_switch,     label: "Zon",       icon: "☀️" },
      { id: c.price_switch,     label: "Schema",    icon: "📅" },
      { id: c.boost_switch,     label: "Boost",     icon: "🚀" },
      { id: c.vacation_switch,  label: "Vakantie",  icon: "🏖️" },
      { id: c.legionella_switch,label: "Legionella",icon: "🦠" },
    ].filter(sw => sw.id);

    const switchHtml = switches.map(sw => {
      const on = this._state(sw.id) === "on";
      return `<button class="sw-btn ${on ? "sw-on" : "sw-off"}" data-entity="${sw.id}">${sw.icon} ${sw.label}</button>`;
    }).join("");

    // Temperature progress bar HTML
    const barFill = `<div style="height:100%;width:${tempPct.toFixed(1)}%;background:${tempColor};border-radius:5px;transition:width 0.6s;"></div>`;
    const targetMarker = (targetPct != null)
      ? `<div style="position:absolute;top:50%;left:${targetPct.toFixed(1)}%;transform:translate(-50%,-50%);width:3px;height:18px;background:${modeColor};border-radius:2px;"></div>`
      : "";
    const barLabels = (targetTemp != null)
      ? `<div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--secondary-text-color);margin-top:3px;">
           <span>${this._fmt(temp, 1)}°C</span>
           <span style="color:${modeColor};font-weight:600;">→ ${targetTemp.toFixed(0)}°C</span>
         </div>`
      : "";

    const powerStr = power && power !== "unknown" ? ` &nbsp;·&nbsp; ⚡ ${this._fmt(power, 0)} W` : "";

    this.innerHTML = `<ha-card>
      <style>
        ha-card { padding:16px; font-family:var(--primary-font-family,sans-serif); }
        .dhw-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
        .dhw-title  { font-size:1rem; font-weight:600; color:var(--primary-text-color); }
        .dhw-badge  { padding:3px 10px; border-radius:99px; font-size:0.75rem; font-weight:600; color:#fff; background:${modeColor}; }
        .dhw-temp-row { display:flex; align-items:center; gap:14px; margin-bottom:10px; }
        .dhw-icon { font-size:2.4rem; line-height:1; flex-shrink:0; width:44px; text-align:center;
          ${isHeating ? "animation:dhw-pulse 1.4s ease-in-out infinite;" : ""} }
        @keyframes dhw-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.2)} }
        .dhw-temp-val { font-size:3rem; font-weight:700; line-height:1; color:${tempColor}; }
        .dhw-temp-unit { font-size:1.3rem; color:var(--secondary-text-color); }
        .dhw-bar-wrap { flex:1; align-self:center; }
        .dhw-bar-track { height:10px; background:var(--divider-color,#e5e7eb); border-radius:5px; overflow:visible; position:relative; }
        .dhw-status { font-size:0.82rem; color:var(--secondary-text-color); margin-bottom:12px; }
        .dhw-stats { display:flex; gap:8px; margin-bottom:12px; }
        .dhw-chip { background:var(--secondary-background-color,#f3f4f6); border-radius:8px; padding:6px 10px; flex:1; text-align:center; }
        .dhw-chip-label { font-size:0.68rem; color:var(--secondary-text-color); margin-bottom:1px; }
        .dhw-chip-value { font-size:0.95rem; font-weight:600; color:var(--primary-text-color); }
        .dhw-next { font-size:0.82rem; color:var(--secondary-text-color); margin-bottom:12px; }
        .dhw-divider { border:none; border-top:1px solid var(--divider-color,#e5e7eb); margin:12px 0; }
        .dhw-switches { display:flex; gap:6px; }
        .sw-btn { border:none; border-radius:8px; padding:8px 4px; font-size:0.82rem; cursor:pointer; font-family:inherit; transition:opacity 0.15s; flex:1; text-align:center; }
        .sw-on  { background:var(--primary-color,#3b82f6); color:#fff; }
        .sw-off { background:var(--secondary-background-color,#e5e7eb); color:var(--secondary-text-color); }
        .sw-btn:hover { opacity:0.8; }
        .manual-btn { border:none; border-radius:10px; padding:10px 16px; font-size:0.88rem; font-weight:600; cursor:pointer; font-family:inherit; width:100%; margin-bottom:8px; transition:all 0.2s; display:flex; align-items:center; justify-content:center; gap:8px; }
        .manual-btn-off { background:var(--secondary-background-color,#e5e7eb); color:var(--primary-text-color); }
        .manual-btn-on  { background:#f97316; color:#fff; box-shadow:0 0 0 3px rgba(249,115,22,0.3); }
        .manual-btn:hover { opacity:0.85; }
      </style>

      <div class="dhw-header">
        <div class="dhw-title">💧 ${title}</div>
        <span class="dhw-badge">${modeLabel}</span>
      </div>

      <div class="dhw-temp-row">
        <div class="dhw-icon">${isHeating ? "🔥" : "💧"}</div>
        <div>
          <span class="dhw-temp-val">${this._fmt(temp, 1, "—")}</span>
          <span class="dhw-temp-unit">°C</span>
        </div>
        <div class="dhw-bar-wrap">
          <div class="dhw-bar-track">
            ${barFill}
            ${targetMarker}
          </div>
          ${barLabels}
        </div>
      </div>

      ${status ? `<div class="dhw-status">${status}${powerStr}</div>` : ""}

      ${chartHtml}

      ${kwh || cost || (power && power !== "unknown") ? `<div class="dhw-stats">
        ${kwh  ? `<div class="dhw-chip"><div class="dhw-chip-label">Sessie kWh</div><div class="dhw-chip-value">${this._fmt(kwh, 2)}</div></div>` : ""}
        ${cost ? `<div class="dhw-chip"><div class="dhw-chip-label">Sessie kosten</div><div class="dhw-chip-value">€${this._fmt(cost, 2)}</div></div>` : ""}
        ${power && power !== "unknown" ? `<div class="dhw-chip"><div class="dhw-chip-label">Vermogen</div><div class="dhw-chip-value">${this._fmt(power, 0)} W</div></div>` : ""}
      </div>` : ""}

      ${nextRel ? `<div class="dhw-next">🚿 Volgende verwarming: <strong>${nextRel}</strong>${plannedMinutes ? ` &nbsp;(~${plannedMinutes} min)` : ""}</div>` : ""}

      <hr class="dhw-divider">
      ${c.manual_switch ? (() => {
        const manOn = this._state(c.manual_switch) === "on";
        return `<button class="manual-btn ${manOn ? "manual-btn-on" : "manual-btn-off"}" id="manual-toggle-btn">
          ${manOn ? "🔥" : "✋"} Handmatig verwarmen &nbsp;<span style="font-size:0.75rem;opacity:0.85;">${manOn ? "● AAN" : "○ UIT"}</span>
        </button>`;
      })() : ""}
      <div class="dhw-switches">${switchHtml}</div>
    </ha-card>`;

    this.querySelectorAll(".sw-btn").forEach(btn =>
      btn.addEventListener("click", () => this._toggleSwitch(btn.dataset.entity))
    );
    const manBtn = this.querySelector("#manual-toggle-btn");
    if (manBtn) manBtn.addEventListener("click", () => this._toggleSwitch(c.manual_switch));
  }

  static getStubConfig() {
    return {
      type: "custom:heatpump-dhw-card",
      title: "Warmtepomp Boiler",
      temp_sensor: "sensor.dhw_boiler_temp",
      mode_sensor: "sensor.dhw_active_mode",
      status_sensor: "sensor.dhw_status_text",
      power_sensor: "sensor.dhw_power_w",
      session_kwh_sensor: "sensor.dhw_session_kwh",
      session_cost_sensor: "sensor.dhw_session_cost",
      next_heating_sensor: "sensor.dhw_next_heating",
      price_forecast_sensor: "sensor.dynamic_electricity_price",
      target_temp_sensor: "",
      cheap_hours: 2,
      solar_switch: "switch.dhw_solar_mode",
      price_switch: "switch.dhw_price_mode",
      boost_switch: "switch.dhw_boost_mode",
      vacation_switch: "switch.dhw_vacation_mode",
      legionella_switch: "switch.dhw_legionella_mode",
      manual_switch: "",
    };
  }
}

customElements.define("heatpump-dhw-card", HeatpumpDhwCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "heatpump-dhw-card",
  name: "Heat Pump DHW Card",
  description: "Dashboard card voor slimme warmtepomp boiler sturing",
  preview: true,
});
