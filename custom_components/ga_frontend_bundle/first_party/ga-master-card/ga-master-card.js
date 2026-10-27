/*
 * ga-master-card — GreenAutarky Master-User Management card (ADR-0006).
 *
 * First-party Lovelace card (vanilla JS, no build step). Lets a flagged
 * Master-User manage their Sub-Users from a dashboard:
 *   - generate one-time invite PINs
 *   - grant/revoke ROOMS (the [sub-user x room] matrix) — the sub-user's dashboard
 *     is GENERATED from them by the ga-home strategy; no dashboard is handed out
 *   - rename rooms (areas)
 *   - Danger zone (KB #169): remove all sub-users. The full site reset is
 *     withdrawn from the card since 1.23.6 (it wiped rooms and heating config
 *     and one of its options left Core + z2m stopped). The card shows a note
 *     to ask support instead and sends no request for it.
 *
 * It is a THIN CLIENT: every action calls the in-Core greenautarky_site
 * endpoints, which enforce the master flag + parent relation server-side.
 * Non-masters get 403 from the API and the card shows the error.
 *
 * Usage in a dashboard:
 *   type: custom:ga-master-card
 */

const API = "greenautarky_site/sub_user";
// Danger zone (KB #169). The household reset is executed in Core.
const API_HOUSEHOLD = "greenautarky_site/household";

/**
 * Text for HTML. Names and texts from Home Assistant (entity names, room names,
 * attributes, stored plans) are escaped before they are rendered, so they show
 * as written. Every first-party card carries this same helper; a test keeps the
 * copies identical.
 */
function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

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
                <div class="muted site-note">Zum vollständigen Löschen deiner
                  Daten wende dich bitte an den Support.</div>
              </div>
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
          <label class="dlg-label"><span>Tippe <code>LÖSCHEN</code> zum Bestätigen</span>
            <input class="hh-confirm" type="text" autocomplete="off" />
          </label>
          <div class="dlg-msg hh-msg"></div>
          <div class="dlg-actions">
            <button type="button" class="btn dlg-cancel">Abbrechen</button>
            <button type="button" class="btn danger hh-go" disabled>Nutzer entfernen</button>
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
        ga-master-card .invite-linkrow { display:flex; gap:8px; margin-bottom:6px; }
        ga-master-card .invite-link { flex:1; min-width:0; font:inherit; padding:6px 8px; }
        ga-master-card table { width:100%; border-collapse:collapse; }
        ga-master-card th, ga-master-card td { text-align:left; padding:6px 4px; border-bottom:1px solid var(--divider-color,#e0e0e0); vertical-align:top; font-size:.92em; }
        ga-master-card .muted { opacity:.6; font-size:.85em; }
        ga-master-card .area-row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        /* ALL THREE AT THE CARD'S OWN SIZE ("increase the font of these 3",
           2026-10-27). A <select> and an <input> take the BROWSER's default font
           rather than the page's, so they rendered a good deal smaller than
           everything around them; the button was on .9em. Only the type is set
           here — the colours stay with the theme, which already renders these
           controls correctly in dark mode. */
        ga-master-card .area-row select,
        ga-master-card .area-row input { font-family:inherit; font-size:1em; padding:7px 9px; }
        ga-master-card .area-row .btn { font-size:1em; }
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
        /* The prompt is ONE sentence. Without the wrapping span its inline
           parts (text, <code>, text) each become a flex row and it reads as
           three stacked lines — caught on baked rc36, K0 2026-07-28. */
        ga-master-card .dlg-label > span { display:block; }
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
    sel.innerHTML = s.areas.map((a) => `<option value="${esc(a.area_id)}">${esc(a.name)}</option>`).join("");

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
                return `<label class="dash"><input type="checkbox" data-uid="${esc(u.user_id)}" data-area="${esc(a.area_id)}"${on}> ${esc(a.name)}</label>`;
              })
              .join("")
          : '<span class="muted">Keine Räume angelegt.</span>';
        const badge = active ? "" : ' <span class="badge">gesperrt</span>';
        const toggle = active ? "Sperren" : "Entsperren";
        return `<tr><td><b>${esc(u.name || "?")}</b>${badge}<br><span class="muted">${esc(u.username || "")}</span>
            <div class="actions">
              <button class="btn small tgl" data-uid="${esc(u.user_id)}" data-enable="${active ? "0" : "1"}">${toggle}</button>
              <button class="btn small danger rm" data-uid="${esc(u.user_id)}" data-name="${esc(u.name || u.username || "")}">Entfernen</button>
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
      out.innerHTML = renderInvite(d);
      const share = out.querySelector(".invite-share");
      if (share) share.addEventListener("click", () => this._shareInvite(d.invite_url));
    } catch (e) {
      this._flash("err", this._errText(e));
    }
  }

  /** The phone's own share sheet where there is one; the clipboard otherwise. */
  async _shareInvite(url) {
    try {
      if (navigator.share) {
        await navigator.share({ title: "Einladung", text: "Einladung zu unserem Zuhause", url });
        return;
      }
      await navigator.clipboard.writeText(url);
      this._flash("ok", "Link kopiert.");
    } catch (e) {
      // Cancelled share sheet, or no clipboard on a plain-http page: the link is
      // still on screen in a field the resident can select and copy by hand.
      const field = this._root.querySelector(".invite-link");
      if (field) field.select();
    }
  }

  // ── Danger zone ─────────────────────────────────────────────────────────
  //
  // The action is gated server-side (master flag). Everything here is UX: it must be hard to fire by
  // accident and honest about what survives. The typed phrase mirrors the
  // operator tool, which makes an operator type the device id.

  _buildDangerZone() {
    const $ = (sel) => this._root.querySelector(sel);

    this._hhDlg = $(".household-dlg");

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

  }

  _phraseOk(value) {
    return (value || "").trim().toUpperCase() === "LÖSCHEN";
  }

  _dlgMsg(sel, kind, text) {
    // Touch ONLY the state class. `sel` (".hh-msg") is a class
    // on this same element; assigning `className` wholesale dropped it, so the
    // next lookup returned null and both Danger Zone buttons threw before
    // sending anything (1.9.0–1.20.0). tests/test_master_card_danger_zone_submits.py
    const el = this._root.querySelector(sel);
    el.classList.remove("ok", "err");
    if (kind) el.classList.add(kind);
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

/**
 * What the master sees after "Einladungs-PIN erzeugen".
 *
 * The server (greenautarky_site >= 2.9.4) sends `invite_url` next to the PIN:
 * `<external_url>/greenautarky-join?pin=…`, the thing the master actually wants
 * to send. Until 2026-09-24 this card showed only the six digits — the link
 * arrived and nothing rendered it. The PIN stays, for reading out over the
 * phone. Without `invite_url` (Home Assistant knows no external URL) the card
 * says so instead of building a link the recipient could not reach.
 *
 * A top-level function, not a method, so tests/js/eval.mjs can run the shipped
 * bytes without a DOM. Everything interpolated is escaped.
 */
function renderInvite(d) {
  const until = new Date(d.expires_at).toLocaleString();
  const pin = `PIN: <code>${esc(d.pin)}</code> <span class="muted">(gültig bis ${esc(until)})</span>`;
  if (!d.invite_url) {
    return pin + `<div class="muted">Kein Link verfügbar — dieses Zuhause hat keine externe Adresse. Bitte den PIN weitergeben.</div>`;
  }
  const url = esc(d.invite_url);
  return (
    `<div class="invite-linkrow">` +
      `<input class="invite-link" type="text" readonly value="${url}" aria-label="Einladungs-Link">` +
      `<button class="btn primary invite-share" type="button">Link teilen</button>` +
    `</div>` +
    `<div><a href="${url}" target="_blank" rel="noopener">${url}</a></div>` +
    pin
  );
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
