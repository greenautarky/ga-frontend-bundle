/*
 * ga-master-card — GreenAutarky Master-User Management card (ADR-0006).
 *
 * First-party Lovelace card (vanilla JS, no build step). Lets a flagged
 * Master-User manage their Sub-Users from a dashboard:
 *   - generate one-time invite PINs
 *   - grant/revoke ROOMS (the [sub-user x room] matrix) — the sub-user's dashboard
 *     is GENERATED from them by the ga-home strategy; no dashboard is handed out
 *   - rename rooms (areas)
 *   - Danger zone (KB #169): remove all sub-users, or erase the whole site.
 *     The household could previously be managed here but not unmade — erasing a
 *     tenant was operator-only, which is the wrong shape for a GDPR erasure
 *     request from the person whose data it is.
 *
 * It is a THIN CLIENT: every action calls the in-Core greenautarky_site
 * endpoints, which enforce the master flag + parent relation server-side.
 * Non-masters get 403 from the API and the card shows the error.
 *
 * Usage in a dashboard:
 *   type: custom:ga-master-card
 */

const API = "greenautarky_site/sub_user";
// Danger zone (KB #169). The household reset is executed in Core; the site
// reset only FILES a request — Core cannot stop Core, so the ga_manager addon
// performs the wipe and reports back through the status endpoint.
const API_HOUSEHOLD = "greenautarky_site/household";
const API_SITE_RESET = "greenautarky_site/site_reset";

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
          <button class="btn primary invite">Einladungs-PIN erzeugen</button>
          <div class="invite-out"></div>

          <h4>Nutzer &amp; Räume</h4>
          <div class="muted">Wähle je Nutzer die Räume, die er sehen darf — sein Dashboard wird daraus erzeugt.</div>
          <div class="users">Lade…</div>

          <h4>Raum umbenennen</h4>
          <div class="area-row">
            <select class="area-sel"></select>
            <input class="area-name" type="text" placeholder="Neuer Name" />
            <button class="btn area-btn">Umbenennen</button>
          </div>

          <h4 class="danger-h">Gefahrenbereich</h4>
          <div class="danger-zone">
            <div class="danger-item">
              <div>
                <b>Nutzer zurücksetzen</b>
                <div class="muted">Entfernt alle Unter-Nutzer mit ihren Konten,
                  Raum-Freigaben und persönlichen Dashboards. Dein Konto, die
                  Räume und die Geräte bleiben.</div>
              </div>
              <button class="btn danger household-reset">Nutzer zurücksetzen…</button>
            </div>
            <div class="danger-item">
              <div>
                <b>Persönliche Daten löschen</b>
                <div class="muted">Löscht alle Daten dieses Zuhauses — Konten,
                  Dashboards, Automationen und den gesamten Verlauf. Das Gerät
                  startet neu und beginnt wieder mit der Ersteinrichtung.</div>
              </div>
              <button class="btn danger site-reset">Alles löschen…</button>
            </div>
          </div>
        </div>
      </ha-card>

      <dialog class="ga-dlg household-dlg">
        <form method="dialog">
          <h3>Alle Unter-Nutzer entfernen?</h3>
          <p>Ihre Konten, Raum-Freigaben und persönlichen Dashboards werden
             gelöscht. Sie können sich danach nicht mehr anmelden.</p>
          <p class="muted">Räume, Geräte, Automationen und dein eigenes Konto
             bleiben. Aufgezeichnete Messwerte gehören zu den Geräten, nicht zu
             den Nutzern — sie bleiben ebenfalls erhalten.</p>
          <label class="dlg-label">Tippe <code>LÖSCHEN</code> zum Bestätigen
            <input class="hh-confirm" type="text" autocomplete="off" />
          </label>
          <div class="dlg-msg hh-msg"></div>
          <div class="dlg-actions">
            <button type="button" class="btn dlg-cancel">Abbrechen</button>
            <button type="button" class="btn danger hh-go" disabled>Nutzer entfernen</button>
          </div>
        </form>
      </dialog>

      <dialog class="ga-dlg site-dlg">
        <form method="dialog">
          <h3>Alle persönlichen Daten löschen?</h3>
          <p><b>Das lässt sich nicht rückgängig machen.</b> Alle Konten,
             Dashboards, Automationen, Einstellungen und der gesamte
             Messwert-Verlauf dieses Zuhauses werden gelöscht.</p>
          <p class="muted">Das Gerät selbst bleibt eingerichtet und mit dem
             Internet verbunden. Nach dem Löschen startet es neu und zeigt die
             Ersteinrichtung.</p>
          <label class="dlg-label">Geräte-PIN vom Aufkleber
            <input class="site-pin" type="text" inputmode="numeric"
                   autocomplete="off" placeholder="000-000" />
          </label>
          <label class="dlg-label">Tippe <code>LÖSCHEN</code> zum Bestätigen
            <input class="site-confirm" type="text" autocomplete="off" />
          </label>
          <label class="dlg-check">
            <input class="site-zigbee" type="checkbox" />
            <span>Auch die Verbindung zu allen Funk-Sensoren trennen. Sie müssen
              danach neu angelernt werden — normalerweise nicht nötig, die
              Sensoren gehören zum Haus.</span>
          </label>
          <div class="dlg-msg site-msg"></div>
          <div class="dlg-actions">
            <button type="button" class="btn dlg-cancel">Abbrechen</button>
            <button type="button" class="btn danger site-go" disabled>Endgültig löschen</button>
          </div>
        </form>
      </dialog>
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
        ga-master-card .badge { font-size:.72em; font-weight:600; padding:1px 6px; border-radius:8px; background: rgba(244,67,54,.15); color: var(--error-color,#c0392b); vertical-align:middle; }
        ga-master-card .actions { margin-top:4px; display:flex; gap:6px; flex-wrap:wrap; }
        ga-master-card .btn { font-family:inherit; font-size:.9em; font-weight:600; padding:8px 14px; border:none; border-radius:20px; cursor:pointer; background: var(--secondary-background-color,#e8e8e8); color: var(--primary-text-color,#212121); }
        ga-master-card .btn:hover { filter:brightness(.97); }
        ga-master-card .btn.primary { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-master-card .btn.small { padding:5px 12px; font-size:.82em; }
        ga-master-card .btn.danger { background: rgba(244,67,54,.12); color: var(--error-color,#c0392b); }
        ga-master-card .btn:disabled { opacity:.45; cursor:not-allowed; }
        ga-master-card h4.danger-h { color: var(--error-color,#c0392b); margin-top:26px; }
        ga-master-card .danger-zone { border:1px solid rgba(244,67,54,.35); border-radius:10px; padding:4px 14px; }
        ga-master-card .danger-item { display:flex; gap:14px; align-items:center; justify-content:space-between; flex-wrap:wrap; padding:12px 0; }
        ga-master-card .danger-item + .danger-item { border-top:1px solid var(--divider-color,#e0e0e0); }
        ga-master-card .danger-item .muted { max-width:46ch; margin-top:2px; }
        ga-master-card .ga-dlg { border:none; border-radius:12px; padding:0; max-width:min(520px,92vw); color: var(--primary-text-color,#212121); background: var(--card-background-color,#fff); }
        ga-master-card .ga-dlg::backdrop { background: rgba(0,0,0,.45); }
        ga-master-card .ga-dlg form { padding:20px; display:flex; flex-direction:column; gap:12px; }
        ga-master-card .ga-dlg h3 { margin:0; font-size:1.1em; }
        ga-master-card .ga-dlg p { margin:0; font-size:.92em; line-height:1.5; }
        ga-master-card .dlg-label { display:flex; flex-direction:column; gap:4px; font-size:.85em; }
        ga-master-card .dlg-label input { font:inherit; padding:8px 10px; border:1px solid var(--divider-color,#e0e0e0); border-radius:8px; background:transparent; color:inherit; }
        ga-master-card .dlg-check { display:flex; gap:8px; align-items:flex-start; font-size:.82em; }
        ga-master-card .dlg-msg { font-size:.85em; min-height:1.2em; }
        ga-master-card .dlg-msg.err { color: var(--error-color,#c0392b); }
        ga-master-card .dlg-msg.ok { color: var(--success-color,#1d7a3a); }
        ga-master-card .dlg-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:4px; }
      </style>`;
    this._root = this;

    this._root.querySelector(".invite").addEventListener("click", () => this._invite());
    this._root.querySelector(".area-btn").addEventListener("click", () => this._renameArea());
    this._buildDangerZone();
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

    // users x ROOMS — the master grants rooms; the dashboard is generated from them
    // by the ga-home strategy. There is no per-user dashboard to hand out anymore.
    const host = this._root.querySelector(".users");
    if (!s.sub_users.length) {
      host.innerHTML = '<div class="muted">Noch keine Unter-Nutzer. Lade jemanden ein.</div>';
      return;
    }
    const rows = s.sub_users
      .map((u) => {
        const assigned = u.rooms || [];
        const active = u.active !== false; // default true if field absent
        const checks = s.areas.length
          ? s.areas
              .map((a) => {
                const on = assigned.indexOf(a.area_id) >= 0 ? " checked" : "";
                return `<label class="dash"><input type="checkbox" data-uid="${u.user_id}" data-area="${a.area_id}"${on}> ${a.name}</label>`;
              })
              .join("")
          : '<span class="muted">Keine Räume angelegt.</span>';
        const badge = active ? "" : ' <span class="badge">gesperrt</span>';
        const toggle = active ? "Sperren" : "Entsperren";
        return `<tr><td><b>${u.name || "?"}</b>${badge}<br><span class="muted">${u.username || ""}</span>
            <div class="actions">
              <button class="btn small tgl" data-uid="${u.user_id}" data-enable="${active ? "0" : "1"}">${toggle}</button>
              <button class="btn small danger rm" data-uid="${u.user_id}" data-name="${(u.name || u.username || "").replace(/"/g, "")}">Entfernen</button>
            </div></td><td>${checks}</td></tr>`;
      })
      .join("");
    host.innerHTML = `<table><tbody>${rows}</tbody></table>`;

    host.querySelectorAll('input[type=checkbox]').forEach((cb) => {
      cb.addEventListener("change", async () => {
        try {
          await this._api("POST", API + "/assign_room", {
            sub_user_id: cb.dataset.uid,
            area_id: cb.dataset.area,
            assigned: cb.checked,
          });
          this._flash("ok", "Raum-Freigabe gespeichert.");
        } catch (e) {
          cb.checked = !cb.checked;
          this._flash("err", this._errText(e));
        }
      });
    });

    // Enable/disable a sub-user's login.
    host.querySelectorAll("button.tgl").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const enable = btn.dataset.enable === "1";
        try {
          await this._api("POST", API + "/set_enabled", {
            sub_user_id: btn.dataset.uid,
            enabled: enable,
          });
          this._flash("ok", enable ? "Nutzer entsperrt." : "Nutzer gesperrt.");
          this._load();
        } catch (e) {
          this._flash("err", this._errText(e));
        }
      });
    });

    // Permanently remove a sub-user (with a confirm).
    host.querySelectorAll("button.rm").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.name || "diesen Nutzer";
        if (!window.confirm(`„${name}" wirklich dauerhaft entfernen? Das Konto wird gelöscht.`)) {
          return;
        }
        try {
          await this._api("POST", API + "/remove", { sub_user_id: btn.dataset.uid });
          this._flash("ok", "Nutzer entfernt.");
          this._load();
        } catch (e) {
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

  // ── Danger zone ─────────────────────────────────────────────────────────
  //
  // Both actions are gated server-side (master flag; the site reset also wants
  // a fresh device PIN). Everything here is UX: it must be hard to fire by
  // accident and honest about what survives. The typed phrase mirrors the
  // operator tool, which makes an operator type the device id.

  _buildDangerZone() {
    const $ = (sel) => this._root.querySelector(sel);

    this._hhDlg = $(".household-dlg");
    this._siteDlg = $(".site-dlg");

    this._root.querySelectorAll(".dlg-cancel").forEach((b) =>
      b.addEventListener("click", () => b.closest("dialog").close())
    );

    // Sub-user reset.
    const hhConfirm = $(".hh-confirm");
    const hhGo = $(".hh-go");
    hhConfirm.addEventListener("input", () => {
      hhGo.disabled = !this._phraseOk(hhConfirm.value);
    });
    $(".household-reset").addEventListener("click", () => {
      hhConfirm.value = "";
      hhGo.disabled = true;
      this._dlgMsg(".hh-msg", "", "");
      this._hhDlg.showModal();
      hhConfirm.focus();
    });
    hhGo.addEventListener("click", () => this._runHouseholdReset(hhGo, hhConfirm.value));

    // Full site reset.
    const sitePin = $(".site-pin");
    const siteConfirm = $(".site-confirm");
    const siteGo = $(".site-go");
    const armSite = () => {
      siteGo.disabled = !(
        this._phraseOk(siteConfirm.value) && this._pinOk(sitePin.value)
      );
    };
    sitePin.addEventListener("input", armSite);
    siteConfirm.addEventListener("input", armSite);
    $(".site-reset").addEventListener("click", () => {
      sitePin.value = "";
      siteConfirm.value = "";
      $(".site-zigbee").checked = false;
      siteGo.disabled = true;
      this._dlgMsg(".site-msg", "", "");
      this._siteDlg.showModal();
      sitePin.focus();
    });
    siteGo.addEventListener("click", () =>
      this._runSiteReset(siteGo, {
        pin: sitePin.value,
        confirm: siteConfirm.value,
        wipe_zigbee_pairing: $(".site-zigbee").checked,
      })
    );
  }

  _phraseOk(value) {
    return (value || "").trim().toUpperCase() === "LÖSCHEN";
  }

  _pinOk(value) {
    return /^\d{6}$/.test((value || "").replace(/[-\s]/g, ""));
  }

  _dlgMsg(sel, kind, text) {
    const el = this._root.querySelector(sel);
    el.className = "dlg-msg " + kind;
    el.textContent = text;
  }

  async _runHouseholdReset(btn, confirm) {
    btn.disabled = true;
    this._dlgMsg(".hh-msg", "", "Entferne Nutzer…");
    try {
      const r = await this._api("POST", API_HOUSEHOLD + "/reset", { confirm });
      this._hhDlg.close();
      const n = (r.removed || []).length;
      this._flash("ok", n ? `${n} Nutzer entfernt.` : "Es gab keine Unter-Nutzer.");
      this._load();
    } catch (e) {
      btn.disabled = false;
      this._dlgMsg(".hh-msg", "err", this._errText(e));
    }
  }

  async _runSiteReset(btn, body) {
    btn.disabled = true;
    this._dlgMsg(".site-msg", "", "Löschung wird gestartet…");
    try {
      await this._api("POST", API_SITE_RESET + "/request", body);
    } catch (e) {
      btn.disabled = false;
      this._dlgMsg(".site-msg", "err", this._errText(e));
      return;
    }
    // Accepted, not done: the addon picks the request up within seconds and
    // stops Home Assistant as its first step. This connection dies with it —
    // which is the expected ending, not a failure to report.
    this._dlgMsg(
      ".site-msg",
      "ok",
      "Löschung läuft. Das Gerät startet gleich neu und zeigt danach die " +
        "Ersteinrichtung. Diese Seite reagiert bis dahin nicht mehr."
    );
    this._pollSiteReset();
  }

  async _pollSiteReset() {
    // Best-effort progress until Core goes down. A failed request here means
    // the wipe has started, so it is never surfaced as an error.
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      let s;
      try {
        s = await this._api("GET", API_SITE_RESET + "/status");
      } catch (e) {
        return;
      }
      const state = (s.status || {}).state;
      if (state === "rejected") {
        this._dlgMsg(
          ".site-msg",
          "err",
          "Das Gerät hat die Löschung abgelehnt: " +
            ((s.status || {}).reason || "unbekannter Grund") +
            ". Bitte erneut versuchen."
        );
        this._root.querySelector(".site-go").disabled = false;
        return;
      }
      if (state === "accepted" && !s.pending) return;
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
