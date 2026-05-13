/**
 * Heat Pump DHW Card — custom Lovelace card
 *
 * Installatie: kopieer naar www/heatpump-dhw-card/heatpump-dhw-card.js
 * Voeg toe aan Lovelace als resource (JavaScript module).
 *
 * Configuratie:
 *   type: custom:heatpump-dhw-card
 *   title: Warmtepomp Boiler        # optioneel
 *   temp_sensor: sensor.dhw_boiler_temp
 *   mode_sensor: sensor.dhw_active_mode
 *   status_sensor: sensor.dhw_status_text
 *   power_sensor: sensor.dhw_power_w
 *   session_kwh_sensor: sensor.dhw_session_kwh
 *   session_cost_sensor: sensor.dhw_session_cost
 *   session_savings_sensor: sensor.dhw_session_savings
 *   monthly_savings_sensor: sensor.dhw_monthly_savings
 *   next_heating_sensor: sensor.dhw_next_heating
 *   heat_up_sensor: sensor.dhw_heat_up_duration_min
 *   solar_switch: switch.dhw_solar_mode
 *   price_switch: switch.dhw_price_mode
 *   boost_switch: switch.dhw_boost_mode
 *   vacation_switch: switch.dhw_vacation_mode
 *   legionella_switch: switch.dhw_legionella_mode
 */

const MODE_COLORS = {
  solar: "#f59e0b",
  boost: "#f97316",
  price: "#22c55e",
  schedule: "#3b82f6",
  legionella: "#ef4444",
  vacation: "#a78bfa",
  idle: "#6b7280",
  manual: "#8b5cf6",
};

const MODE_ICONS = {
  solar: "mdi:solar-power",
  boost: "mdi:rocket-launch",
  price: "mdi:tag-outline",
  schedule: "mdi:shower-head",
  legionella: "mdi:bacteria",
  vacation: "mdi:beach",
  idle: "mdi:water-boiler-off",
  manual: "mdi:hand",
};

const MODE_LABELS = {
  solar: "Zonne-energie",
  boost: "Boost",
  price: "Lage prijs",
  schedule: "Douche schema",
  legionella: "Legionella run",
  vacation: "Vakantie",
  idle: "Standby",
  manual: "Handmatig",
};

class HeatpumpDhwCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    if (!config.temp_sensor) {
      throw new Error("temp_sensor is vereist");
    }
    this._config = config;
  }

  getCardSize() {
    return 4;
  }

  _state(entityId) {
    if (!entityId || !this._hass) return null;
    const s = this._hass.states[entityId];
    return s ? s.state : null;
  }

  _attr(entityId, attr) {
    if (!entityId || !this._hass) return null;
    const s = this._hass.states[entityId];
    return s ? s.attributes[attr] : null;
  }

  _fmt(val, decimals = 1, fallback = "—") {
    if (val == null || val === "unknown" || val === "unavailable") return fallback;
    const n = parseFloat(val);
    return isNaN(n) ? fallback : n.toFixed(decimals);
  }

  _tempColor(temp) {
    const t = parseFloat(temp);
    if (isNaN(t)) return "#6b7280";
    if (t < 35) return "#3b82f6";
    if (t < 45) return "#22c55e";
    if (t < 55) return "#f59e0b";
    return "#ef4444";
  }

  _tempPercent(temp) {
    const t = parseFloat(temp);
    if (isNaN(t)) return 0;
    return Math.min(100, Math.max(0, ((t - 20) / (80 - 20)) * 100));
  }

  _formatDatetime(isoStr) {
    if (!isoStr || isoStr === "unknown") return "—";
    const d = new Date(isoStr);
    if (isNaN(d)) return "—";
    const now = new Date();
    const diffMs = d - now;
    const diffMin = Math.round(diffMs / 60000);
    if (diffMin < 0) return "Nu";
    if (diffMin < 60) return `over ${diffMin} min`;
    if (diffMin < 1440) {
      const h = Math.floor(diffMin / 60);
      const m = diffMin % 60;
      return `${d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })} (over ${h}u${m > 0 ? m + "m" : ""})`;
    }
    return d.toLocaleDateString("nl-NL", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  }

  async _toggleSwitch(entityId) {
    if (!entityId || !this._hass) return;
    const state = this._state(entityId);
    const svc = state === "on" ? "turn_off" : "turn_on";
    await this._hass.callService("switch", svc, { entity_id: entityId });
  }

  _render() {
    if (!this._config || !this._hass) return;

    const c = this._config;
    const temp = this._state(c.temp_sensor);
    const mode = this._state(c.mode_sensor) || "idle";
    const status = this._state(c.status_sensor) || "—";
    const power = this._state(c.power_sensor);
    const kwh = this._state(c.session_kwh_sensor);
    const cost = this._state(c.session_cost_sensor);
    const savings = this._state(c.session_savings_sensor);
    const monthlySavings = this._state(c.monthly_savings_sensor);
    const nextHeating = this._state(c.next_heating_sensor);
    const heatUp = this._state(c.heat_up_sensor);

    const modeColor = MODE_COLORS[mode] || "#6b7280";
    const modeLabel = MODE_LABELS[mode] || mode;
    const tempColor = this._tempColor(temp);
    const tempPct = this._tempPercent(temp);
    const title = c.title || "Warmtepomp Boiler";

    const switches = [
      { id: c.solar_switch, label: "Zon", icon: "☀️" },
      { id: c.price_switch, label: "Prijs", icon: "💶" },
      { id: c.boost_switch, label: "Boost", icon: "🚀" },
      { id: c.vacation_switch, label: "Vakantie", icon: "🏖️" },
      { id: c.legionella_switch, label: "Legionella", icon: "🦠" },
    ];

    const switchHtml = switches
      .filter((sw) => sw.id)
      .map((sw) => {
        const on = this._state(sw.id) === "on";
        return `
        <button
          class="sw-btn ${on ? "sw-on" : "sw-off"}"
          data-entity="${sw.id}"
          title="${sw.label} ${on ? "uitschakelen" : "inschakelen"}"
        >${sw.icon} ${sw.label}</button>`;
      })
      .join("");

    this.innerHTML = `
    <ha-card>
      <style>
        ha-card {
          padding: 16px;
          font-family: var(--primary-font-family, sans-serif);
        }
        .card-title {
          font-size: 1rem;
          font-weight: 600;
          color: var(--primary-text-color);
          margin-bottom: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .mode-badge {
          display: inline-block;
          padding: 2px 10px;
          border-radius: 99px;
          font-size: 0.75rem;
          font-weight: 600;
          color: white;
          background: ${modeColor};
        }
        .temp-block {
          display: flex;
          align-items: flex-end;
          gap: 12px;
          margin: 8px 0 16px;
        }
        .temp-value {
          font-size: 3.5rem;
          font-weight: 700;
          line-height: 1;
          color: ${tempColor};
        }
        .temp-unit {
          font-size: 1.5rem;
          color: var(--secondary-text-color);
          margin-bottom: 6px;
        }
        .temp-bar-wrap {
          flex: 1;
          height: 12px;
          background: var(--divider-color, #e5e7eb);
          border-radius: 6px;
          overflow: hidden;
          align-self: center;
        }
        .temp-bar {
          height: 100%;
          width: ${tempPct}%;
          background: ${tempColor};
          border-radius: 6px;
          transition: width 0.5s ease;
        }
        .status-row {
          font-size: 0.85rem;
          color: var(--secondary-text-color);
          margin-bottom: 12px;
        }
        .stats-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
          margin-bottom: 14px;
        }
        .stat-box {
          background: var(--secondary-background-color, #f3f4f6);
          border-radius: 10px;
          padding: 8px 10px;
          text-align: center;
        }
        .stat-label {
          font-size: 0.7rem;
          color: var(--secondary-text-color);
          margin-bottom: 2px;
        }
        .stat-value {
          font-size: 1rem;
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .next-row {
          font-size: 0.82rem;
          color: var(--secondary-text-color);
          margin-bottom: 14px;
          display: flex;
          gap: 6px;
          align-items: center;
        }
        .switches {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .sw-btn {
          border: none;
          border-radius: 8px;
          padding: 5px 10px;
          font-size: 0.78rem;
          cursor: pointer;
          font-family: inherit;
          transition: opacity 0.15s;
        }
        .sw-on {
          background: var(--primary-color, #3b82f6);
          color: white;
        }
        .sw-off {
          background: var(--secondary-background-color, #e5e7eb);
          color: var(--secondary-text-color);
        }
        .sw-btn:hover { opacity: 0.8; }
        .divider {
          border: none;
          border-top: 1px solid var(--divider-color, #e5e7eb);
          margin: 12px 0;
        }
        .savings-row {
          display: flex;
          justify-content: space-between;
          font-size: 0.82rem;
          color: var(--secondary-text-color);
        }
        .savings-value {
          color: #22c55e;
          font-weight: 600;
        }
      </style>

      <div class="card-title">
        💧 ${title}
        <span class="mode-badge">${modeLabel}</span>
      </div>

      <div class="temp-block">
        <div>
          <span class="temp-value">${this._fmt(temp, 1, "—")}</span>
          <span class="temp-unit">°C</span>
        </div>
        <div class="temp-bar-wrap">
          <div class="temp-bar"></div>
        </div>
      </div>

      <div class="status-row">📡 ${status}${power && power !== "unknown" ? ` &nbsp;·&nbsp; ⚡ ${this._fmt(power, 0)} W` : ""}</div>

      <div class="stats-grid">
        <div class="stat-box">
          <div class="stat-label">Sessie kWh</div>
          <div class="stat-value">${this._fmt(kwh, 2)}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Sessie kosten</div>
          <div class="stat-value">€${this._fmt(cost, 3)}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Sessie besparing</div>
          <div class="stat-value" style="color:#22c55e">€${this._fmt(savings, 3)}</div>
        </div>
      </div>

      ${
        nextHeating && nextHeating !== "unknown"
          ? `<div class="next-row">🚿 Volgende verwarming: <strong>${this._formatDatetime(nextHeating)}</strong>${heatUp ? ` &nbsp;(opwarmtijd ~${this._fmt(heatUp, 0)} min)` : ""}</div>`
          : ""
      }

      <hr class="divider">

      <div class="switches">
        ${switchHtml}
      </div>

      ${
        monthlySavings
          ? `<hr class="divider">
        <div class="savings-row">
          <span>💰 Maandelijkse besparing</span>
          <span class="savings-value">€${this._fmt(monthlySavings, 2)}</span>
        </div>`
          : ""
      }
    </ha-card>
    `;

    // Attach switch toggle listeners
    this.querySelectorAll(".sw-btn").forEach((btn) => {
      btn.addEventListener("click", () => this._toggleSwitch(btn.dataset.entity));
    });
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
      session_savings_sensor: "sensor.dhw_session_savings",
      monthly_savings_sensor: "sensor.dhw_monthly_savings",
      next_heating_sensor: "sensor.dhw_next_heating",
      heat_up_sensor: "sensor.dhw_heat_up_duration_min",
      solar_switch: "switch.dhw_solar_mode",
      price_switch: "switch.dhw_price_mode",
      boost_switch: "switch.dhw_boost_mode",
      vacation_switch: "switch.dhw_vacation_mode",
      legionella_switch: "switch.dhw_legionella_mode",
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
