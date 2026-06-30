/*
 * ga-master-card — GreenAutarky Master-User Management card (ADR-0006).
 *
 * First-party Lovelace card (vanilla JS, no build step). Lets a flagged
 * Master-User manage their Sub-Users from a dashboard:
 *   - generate one-time invite PINs
 *   - assign/unassign dashboards (the [sub-user x dashboard] matrix)
 *   - rename rooms (areas)
 *
 * It is a THIN CLIENT: every action calls the in-Core greenautarky_onboarding
 * endpoints, which enforce the master flag + parent relation server-side.
 * Non-masters get 403 from the API and the card shows the error.
 *
 * Usage in a dashboard:
 *   type: custom:ga-master-card
 */

const API = "greenautarky_onboarding/sub_user";

class GaMasterCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
      this._load();
    }
  }

  getCardSize() {
    return 6;
  }

  async _api(method, path, body) {
    // hass.callApi(method, "<path without /api>", data) — auth + JSON handled.
    return this._hass.callApi(method, path, body);
  }

  _flash(kind, text) {
    const m = this._root.querySelector(".msg");
    m.className = "msg " + kind;
    m.textContent = text;
    if (this._t) clearTimeout(this._t);
    this._t = setTimeout(() => {
      m.className = "msg";
    }, 4000);
  }

  _build() {
    this.innerHTML = `
      <ha-card header="Haushalt verwalten">
        <div class="card-content">
          <div class="msg"></div>

          <h4>Neuen Nutzer einladen</h4>
          <mwc-button raised class="invite">Einladungs-PIN erzeugen</mwc-button>
          <div class="invite-out"></div>

          <h4>Nutzer &amp; Dashboards</h4>
          <div class="users">Lade…</div>

          <h4>Raum umbenennen</h4>
          <div class="area-row">
            <select class="area-sel"></select>
            <input class="area-name" type="text" placeholder="Neuer Name" />
            <mwc-button class="area-btn">Umbenennen</mwc-button>
          </div>
        </div>
      </ha-card>
      <style>
        ga-master-card .card-content { padding: 16px; }
        ga-master-card h4 { margin: 18px 0 8px; }
        ga-master-card .msg { display:none; padding:8px 10px; border-radius:8px; margin-bottom:8px; font-size:.9em; }
        ga-master-card .msg.ok { display:block; background: rgba(76,175,80,.15); color: var(--success-color,#1d7a3a); }
        ga-master-card .msg.err { display:block; background: rgba(244,67,54,.15); color: var(--error-color,#c0392b); }
        ga-master-card .invite-out { margin-top:8px; }
        ga-master-card table { width:100%; border-collapse:collapse; }
        ga-master-card th, ga-master-card td { text-align:left; padding:6px 4px; border-bottom:1px solid var(--divider-color,#e0e0e0); vertical-align:top; font-size:.92em; }
        ga-master-card .muted { opacity:.6; font-size:.85em; }
        ga-master-card .area-row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        ga-master-card label.dash { display:block; font-weight:400; margin:2px 0; }
        ga-master-card code { font-weight:700; }
      </style>`;
    this._root = this;

    this._root.querySelector(".invite").addEventListener("click", () => this._invite());
    this._root.querySelector(".area-btn").addEventListener("click", () => this._renameArea());
  }

  async _load() {
    try {
      const data = await this._api("GET", API + "/list");
      this._state = data;
      this._render();
    } catch (e) {
      this._flash("err", this._errText(e));
    }
  }

  _errText(e) {
    // hass.callApi rejects with the response body on non-2xx.
    if (e && e.body && e.body.message) return e.body.message;
    if (e && e.message) return e.message;
    return "Fehler";
  }

  _render() {
    const s = this._state || { sub_users: [], dashboards: [], areas: [] };

    // areas
    const sel = this._root.querySelector(".area-sel");
    sel.innerHTML = s.areas.map((a) => `<option value="${a.area_id}">${a.name}</option>`).join("");

    // users x dashboards
    const host = this._root.querySelector(".users");
    if (!s.sub_users.length) {
      host.innerHTML = '<div class="muted">Noch keine Unter-Nutzer. Lade jemanden ein.</div>';
      return;
    }
    const rows = s.sub_users
      .map((u) => {
        const assigned = u.dashboards || [];
        const checks = s.dashboards.length
          ? s.dashboards
              .map((d) => {
                const on = assigned.indexOf(d.url_path) >= 0 ? " checked" : "";
                return `<label class="dash"><input type="checkbox" data-uid="${u.user_id}" data-url="${d.url_path}"${on}> ${d.title}</label>`;
              })
              .join("")
          : '<span class="muted">Keine Dashboards.</span>';
        return `<tr><td><b>${u.name || "?"}</b><br><span class="muted">${u.username || ""}</span></td><td>${checks}</td></tr>`;
      })
      .join("");
    host.innerHTML = `<table><tbody>${rows}</tbody></table>`;

    host.querySelectorAll('input[type=checkbox]').forEach((cb) => {
      cb.addEventListener("change", async () => {
        try {
          await this._api("POST", API + "/assign_dashboard", {
            sub_user_id: cb.dataset.uid,
            url_path: cb.dataset.url,
            assigned: cb.checked,
          });
          this._flash("ok", "Dashboard-Zuweisung gespeichert.");
        } catch (e) {
          cb.checked = !cb.checked;
          this._flash("err", this._errText(e));
        }
      });
    });
  }

  async _invite() {
    try {
      const d = await this._api("POST", API + "/invite", {});
      const out = this._root.querySelector(".invite-out");
      out.innerHTML = `PIN: <code>${d.pin}</code> <span class="muted">(gültig bis ${new Date(
        d.expires_at
      ).toLocaleString()})</span>`;
    } catch (e) {
      this._flash("err", this._errText(e));
    }
  }

  async _renameArea() {
    const area_id = this._root.querySelector(".area-sel").value;
    const name = this._root.querySelector(".area-name").value.trim();
    if (!area_id || !name) {
      this._flash("err", "Raum + neuer Name nötig.");
      return;
    }
    try {
      await this._api("POST", API + "/rename_area", { area_id, name });
      this._flash("ok", "Raum umbenannt.");
      this._root.querySelector(".area-name").value = "";
      this._load();
    } catch (e) {
      this._flash("err", this._errText(e));
    }
  }
}

if (!customElements.get("ga-master-card")) {
  customElements.define("ga-master-card", GaMasterCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-master-card",
  name: "GA Master-User Verwaltung",
  description: "Verwalte Unter-Nutzer, Dashboards und Räume (ADR-0006).",
});
