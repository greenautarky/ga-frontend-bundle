# Changelog

## 1.27.0 — 2026-11-25

**Boost from the room's own card, in one tap** (asked for 2026-11-17).

It was already possible and nobody could find it. `ga_heating.boost` has always taken an `entity_id`, and the whole-home card can boost a selection of rooms — but behind a room picker, on a card whose own header calls it "the whole-home heating controls". Meanwhile the room's own card had shown a *running* boost since 1.19.x, with a `Beenden` button beside it: a resident who found the stop had nowhere to look for the start.

- **A Boost button on `ga-thermostat-card`**, on its own row directly under KI / MANUEL / AUS. One tap asks for 15 minutes — the same number the house button uses, pinned by a test so the two cannot drift. `boost_minutes:` overrides it for a hand-written dashboard, clamped to 1…240 so a typo is a short boost rather than a service call ga_heating rejects.
- It reaches every layout, because it rides on `_modeRow` — `classic`, `setpoint` and `dial` all compose through it.
- **Hidden exactly when a press could not win**, which is ga_heating's own precedence (window > ichb > boost > absence > slot): no button with a window open or a balancing run in progress, because the service would accept the press and the valves would not move — the same lie as a `Beenden` on an open window. During an **Urlaub** it stays, since a boost outranks an absence. While a boost runs, the row above is the control.
- The press always sends an explicit `temperature`, and it is **3 °C above whichever is higher, the room or the setpoint it is on**, capped at the room's `max_temp`. 3 is ga_heating's own `BOOST_STEP`. Above the *room*, not merely above the setpoint, because an AUS room's radiators sit at their frost value and `frost + 3` is 11 °C in a room at 19 — a press that sent that would be a button that did nothing.
- **While a boost runs the card shows the word `Boost` where the target number goes**, and drops the controls that cannot move it — the − / + in `classic` and `setpoint`, the drag on the `dial`, and the `ZIEL` caption. The row beneath still says *Boost noch 14 min — bis 10:05* with its `Beenden`, and the controls come back with it.

### Why it no longer asks for 30 °C, and shows a word instead

Both boost buttons used to send the room's `max_temp` to emulate "open the valves 100 %". It did open them — and every room card then read **30.0**, because `target_temperature` reports the setpoint the *radiators* are on, not what the plan intends. A resident reading that as "this room is being driven to 30 degrees" is reading the number correctly ("30 is not accurate, we dont want to reach 30", 2026-11-18).

A TRV calls for heat on the gap between its setpoint and what it reads, and a room does not climb 3 K in fifteen minutes — so for a run this short, 3 °C holds the valve open exactly as 30 did, while asking for nothing that could be overshot into if the run is ever extended. What it deliberately does **not** touch is `valve_opening_degree`: that is how far the valve opens once the TRV has decided to heat, not the lever that makes it decide, and on this hardware it never moves off 100 anyway (14 827 samples over 30 days on one device, all 100.0).

The number is honest again at 3 °C, but it is still the *override's* number rather than the room's own decision, and `24.0` on a room somebody set to 21 invites the same question `30.0` did. So for the minutes it runs, the slot says what is happening instead of to what. The − / + go with it because they provably cannot move it: `_apply` keeps writing the override's value to the valves for as long as the boost outranks the room's stored decision, so a press lands, is kept for afterwards, and shows nothing meanwhile. This card already hides a control that cannot win — the Boost button itself, with a window open.

The whole-home card changed with it, including its wording: "voll aufgedreht" and "Ventile ganz offen" were describing the 30 °C emulation.

**Nothing changed about where a boost hands the room back to.** It lives in ga_heating's `_overrides` and never touched the stored mode or `manual_until`, so a room boosted out of MANUELL returns to MANUELL at its own setpoint with its original clock still running, and one boosted out of KI returns to KI on the current slot. A manual period that would have ended during the boost ends there, which is right: a boost should not extend a decision the resident time-boxed.

### Why it is not in the mode row, and not in the timer row

`KI / MANUEL / AUS` come from `hvac_modes` and are states a room can be left in; a boost runs *over* whichever is chosen and hands the room back. In that row it would read as a fourth state, and the row's own `s.state === m` highlight has nothing true to say about it.

The manual/override row was the tempting home, because `Beenden` already lives there — but that row renders **nothing** for a room following its plan, deliberately, so such a room grows no empty timer (`test_no_override_renders_nothing`). Reaching the common case from inside it would have meant breaking that rule, so the button got a row of its own.

### Tests

40 cases in `tests/test_thermostat_room_boost.py`, running the shipped bytes in a VM. Each guard was verified red against a mutation of the thing it guards: the row not appended to `_modeRow` (2 red), the precedence rule dropped (3 red), the button missing from the delegated click selector (2 red), the temperature omitted from the call (2 red), the duration left unclamped (2 red), and for the change below: the room ignored in favour of the setpoint alone, the cap dropped, `max_temp` sent again, the rounding removed, the number left in place in each of the three layouts, the − / + and the dial drag left live, the pending value painted over the word, an inactive boost counted as running, and the two cards' step allowed to drift (14 mutations, every one red).

One of them found a defect in the first version of this change before it ever ran on a device: `Number(null)` is `0` and passes `Number.isFinite`, so a room publishing `max_temp: null` would have been boosted to **0 °C** — the exact opposite of the press. The guard is now `isFinite(max) && max > 0`.

## 1.25.0 — 2026-11-25

- Zigbee list (Odoo #1905): a device with a GA sticker reads "Thermostat (TRV-SON-12)" instead of "Thermostat 1". Only in this list; HA names are unchanged. When the device has no label file, the list says so. Needs the greenautarky_site version that sends `label`; against an older one the list looks as before.

## 1.23.11 — 2026-11-16

The resident's Einstellungen page (Odoo #2144, #2145, #2146), from the K31 hand test of BOSv1.6.1-rc1. Needs greenautarky_site >= 2.13.0 (the two new blocks read its endpoints; against an older one each block says "nicht verfügbar" and nothing else changes) and ga_manager >= 0.277.6 for the release headline.

- Zigbee devices (#2144): a table before the Gefahrenbereich with every Zigbee device's room, battery % and LQI, sorted by room. A weak LQI (< 50) and a low battery (<= 20 %) are marked with colour and text; a device without a room says "ohne Raum". Read-only.
- Software tile (#2145): before the Gefahrenbereich, the GA release bundle (e.g. BOSv1.6.1-rc2) as headline, expandable to every version the device runs (OS, Supervisor, Core, plugins, every add-on, every custom integration). Re-asked on every load; a missing release says so instead of showing a default.
- No search, no Assist for a resident (#2146): new early-injected asset `ga-resident-chrome` hides the top-bar magnifier and Assist buttons for a non-admin user and neutralises the A / E / C / D / Ctrl+K shortcuts. Typing the letter "a" in a field still works. The admin / service view is unchanged. A direct `?conversation=1` link still opens Assist.

## 1.23.10 — 2026-11-12

Room view polish by @ahmad-greenautarky, plus a sidebar fix.

- Radiator curve (#66): a room that has not published its valves yet draws no curve, rather than the radiator's.
- Room readings (#65): the room's readings go left again, its temperature is bold, and a phone can ask what a number is.
- Child lock (#67): a locked thermostat says so, with a padlock after the room name.
- Sidebar default (#68): ga-sidebar-default no longer fires `hass-dock-sidebar` into a half-hydrated app (Odoo #1743). On Core 2026.10.4.4 the app's handler threw `Cannot read properties of undefined (reading 'entities')` while `hass` was still partial; the error escapes the script's try/catch (dispatchEvent reports a listener's exception as uncaught). The nudge now waits for `hass.entities`; the existing 250 ms retry covers the wait.

## 1.23.9 — 2026-11-10

A room with no usable thermometer charts what actually drives it.

- Temperature for a room without a usable sensor (#62, by @ahmad-greenautarky): the 24 h chart draws the house mean the engine names in `house_temperature_entity` instead of the radiator valve's own reading; a thermometer that has stopped answering hands its curve to the mean as well. The valve stays the last resort: in a house where no room has a sensor there is no mean, and the room keeps the valve. **Needs ga-heating >= 0.14.1**; an older engine names no mean and the room keeps its valve.
- One curve, no legend (#62): a chart with a single curve drops its legend; two curves keep it, labelled "Raum Temperatur" / "Raum Luftfeuchtigkeit" next to the outdoor curve.

## 1.23.8 — 2026-10-28

Outdoor data without a per-device dashboard edit, plus the UI session merged as #57 and the boost change #58.

- Outdoor pair by default (#61, bundle half of ga_manager #371): the room view's `outdoor_temperature` / `outdoor_humidity` default to `sensor.aussentemperatur` / `sensor.aussenluftfeuchtigkeit`, the ids ga_manager >= 0.263.0 provisions from the met.no entry. Still verified against `hass.states`: a device without the entities draws no badge and no second curve; `false` switches the pair off; a string overrides.
- Badge row (#57, by @ahmad-greenautarky): the room's own readings open the row, each group carries one icon (house-import / house-export) instead of words, the split counts the room's group.
- Wartung (#57): one row per device, dated, scrollable. A climate sensor that stops talking is one line, not two; the radio verdict is ga-heating's `link_weak` where the engine publishes it (ga-heating 0.13.8), the per-packet path otherwise; a silent device no longer collects a stale "radio weak" row.
- Humidity for a room without a hygrometer (#57): the 24 h chart draws the house mean the engine names, instead of a blank; an older engine names nothing and the room keeps its blank.
- Boost (#58): fifteen minutes instead of five, so the run outlasts the time a TRV needs to open and the radiator to make itself felt.
- Docs (#59): comments, changelog and tests refer to test devices generically.

> **Needs ga_manager >= 0.263.0** for the outdoor entities (BOSv1.5.3 target); on older ga_manager the room view degrades as before, no "unknown" badge. **ga-heating 0.13.8** for the radio verdict and the humidity mean; older engines fall back to the previous behaviour.

## 1.23.7 — 2026-10-21

Services rebuild and "Urlaub as a plan" by @ahmad-greenautarky, merged as #55. Developed card by card against a test device.

- Services: every action is the whole flat — the room picker is gone, so the scope can never disagree with the buttons. Boost / Alle → KI / Alle AUS sit in one row at every width (they used to stack on phones). Hydraulic balancing is shown only when the strategy sets `show_ichb: true`. Explanations moved behind "i" buttons.
- Urlaub: its own section, the form is the section (no "Bearbeiten"); date fields keep what is typed (the markup no longer carries values, so a state push no longer rebuilds the field being edited). "Krankheit" and the "Aus · Frostschutz" option are removed; times are hourly.
- Room view: the thermostat card carries the room name in its header; two groups (readings / control); optional outdoor temperature and humidity badges from the strategy options; fixed chart colours. Wartung no longer lists late valves.
- Heating card: "Urlaubsplan aktiv bis …" banner and a read-only plan while a holiday runs. The log names the account that acted.
- Wording: "Sonderplan" → "Urlaub", "MANUEL" → "MANUELL".
- Removed for residents (support note): room picker, Krankheit, Frostschutz checkbox, "Bearbeiten", quarter-hour times, valves_late rows.

> **Needs ga_heating 0.13.7** for the held holiday plan and the account name in the log. On ga_heating 0.13.6 the card still works (same absence API); the "Urlaubsplan aktiv" banner then locks the editor although the plan is not actually held there.

Known follow-ups are tracked in Odoo #1316 (Alle → KI ends a running holiday without saying so; no confirmation on Alle AUS).

## 1.23.6 — 2026-10-14

Protective hotfix: the full-site reset is withdrawn from the "Haushalt verwalten" card.

- The "Alles löschen…" action and its dialog are removed from the Gefahrenbereich. In its place the card shows: "Zum vollständigen Löschen deiner Daten wende dich bitte an den Support." The card no longer sends any request to `greenautarky_site/site_reset`.
- The "Auch die Verbindung zu allen Funk-Sensoren trennen" option is gone with it.
- Why: the full reset is being reworked; until then deletion of all personal data goes through support.
- Unchanged: "Nutzer zurücksetzen" and everything else on the card.
- Tests: `tests/browser/master-card-danger-zone.mjs` renders the shipped card and asserts there is no site-reset button, dialog or radio-sensor option, a support note, and that no click reaches `site_reset`; the household reset still sends its request.

## 1.23.5 — 2026-10-08

UI polish by @ahmad-greenautarky, merged as #52.

- Each room's view is headed by the room's name instead of "Heizung"; the readings carry an "Aktuell" label; the section headings (Heizplan, Verlauf, Geräte, Aktivität) get icons. The "Profil" view is labelled "Services" — its path is unchanged, so bookmarks keep working.
- Heizplan: when a plan is edited, the old and the new plan are drawn on one scale and the size of each change is shown, instead of a dashed marker behind the edited bar.
- Aktivität shows 5 entries by default (was 3) and lists balancing runs by name ("Hydraulischer Abgleich gestartet / beendet / abgebrochen").
- The thermostat card labels its big number "Ziel"; Wartung gets an icon in its heading (only `mdi:` icon names are rendered).

> **Needs ga_heating 0.13.6** for the balancing-run lines in Aktivität. With older ga_heating the log shows setpoint and mode changes as before.

## 1.23.4 — 2026-10-08

- Wartung: a room sensor that has stopped talking is listed first, with how long it has been silent ("Temperatursensor meldet nicht (seit 4 h)"). The card renders ga_heating's `sensor_silent` verdict and re-decides nothing (Ahmad, #50).

> **Needs ga_heating 0.13.5** (`sensor_silent`). Older ga_heating publishes nothing, and the section shows batteries, link quality and late valves as before.

## 1.23.3 — 2026-10-07

- Names and texts from Home Assistant are escaped before rendering in the GA cards.

## 1.23.2 — 2026-10-07

> **The radio-health rows read ga_heating's `valves_late`, published from
> ga_heating 0.13.2; the "own setpoint" line needs 0.13.3.** Older ga_heating
> publishes neither, and the Wartung section then shows batteries and link
> quality only.

- **A room without a hygrometer shows the house humidity** (Ahmad, #45). The
  humidity badge bound to the room's own sensor or showed nothing; a room without
  one now binds to the climate entity, which carries ga_heating's
  `current_humidity` — the average of the rooms that have a hygrometer. A room
  with its own sensor keeps it, and a house with none grows no badge.

- **Wartung reports radio health** (Ahmad, #46). A thermostat or sensor with a
  weak Zigbee link gets a line ("Funkverbindung schwach" / "sehr schwach"); an
  unreported link quality says nothing. A radiator that answered ga_heating's own
  write 30 s or more late is named with its lag ("antwortet verzögert (58 s)") —
  the reason a room can drop to MANUEL after nobody touched it.

- **A radiator that answered with a setpoint of its own is named too**
  ("setzt eigenen Sollwert"). Such an answer is on time, so the lag rule hid it;
  ga_heating 0.13.3 counts these per radiator. A radiator that did both gets one
  line saying both.

- **Worst first across every kind.** Within a level a battery is listed before a
  weak link, and a weak link before a late or substituting radiator.

## 1.23.1 — 2026-10-06

- **"Aktivität" is shown in every room by default.** The change-log card was off by
  default "while new", and greenautarky_site writes the strategy without options, so a
  device test on BOSv1.4.0-rc6 found it on no room view of any device. `change_log: false`
  still hides it.

## 1.23.0 — 2026-10-06

> **Requires ga_heating 0.13.0 for the balancing controls; without it the
> section is hidden.** The Profil card shows "Hydraulischer Abgleich" only when
> Home Assistant lists the `ga_heating.ichb` service, which ga_heating 0.13.0
> registers. On 0.12.x the card shows everything else and no balancing button.

- **A running boost can be ended where it is running.** The override row said
  a boost was going and how long it had left, and offered no way out; the only
  escape was to press KI or AUS, which is not the same thing — an override never
  replaced the room's decision, so cancelling it puts the room back exactly as
  it was, while pressing KI writes a new decision over the old one and a room
  that was AUS comes back heating. There is a Beenden button on a boost and on a
  Sonderplan, and deliberately none on an open window: that ends when the
  contact closes, and a button saying otherwise is a lie about a contact. The
  Profil card can end a running boost too: "Boost beenden" ends it in every
  room that has one, whatever the room selection says, because it sits under
  the line that counts those rooms.

- **Hydraulischer Abgleich can be started from the Profil card.** ga_heating had
  the services; nothing on screen called them, so a balancing run could only be
  started from Developer Tools. The cancel button appears only while a run is
  going. A run is also named in the room card it is running in — first in the
  row, since ga_heating ranks window > ichb > boost — with no Beenden there,
  because `cancel_ichb` ends the hour for every room and a button inside one
  room's card would silently stop all six.

- **The card warns before a balancing hour is wasted.** The run measures each
  radiator's catch-up rate at a common flow, so every room needs somewhere to
  climb; the first run on a real flat produced no rate for any radiator because
  three rooms sat at 25.4, 25.9 and 25.0 °C. Two limits, because a warm room
  spoils the hour two different ways: above 26 °C (the 30 °C target less 4 K of
  headroom) a room cannot be measured at all and is named in red, and above
  21 °C it still can be but the rates compress together, which is a
  recommendation rather than a refusal. Said both on the heading, where a
  resident looks before deciding, and on the press, which is what they get if
  they did not.

- **A tap on a room chip is no longer lost while a countdown runs.** The Profil
  card re-rendered itself every second, always, and rebuilt the room chips each
  time, so a press held across a tick went down on one button and came up over
  its replacement. The clock now runs only while a boost or a balancing run
  counts down, a tick updates only the countdown text, and the chips and form
  fields are rebuilt only when what they show changes. The countdown also drops
  the red "too warm" colour once a run is going, and "Boost beenden" reports the
  rooms it actually reached ("in 1 Raum", or "1 von 2 … nicht erreicht: …").

- **Low batteries are a class and a name, not a percentage.** The thermostat
  card showed one battery number at the top with no indication whose it was.
  There is now a "Wartung" section under Aktivität listing every sensor in the
  room that needs attention — valves and thermometers alike — named by its GA
  label with the padding stripped (`THD-SON-202`), at "Batterie niedrig" below
  30 % and "Batterie fast leer" below 20 %. Built from the room's own devices,
  so a resident's phone cannot appear in it. Heating faults are meant to join
  them here rather than become a second list elsewhere.

- **Speichern and Verwerfen stop disagreeing with the plan on screen.** A
  resident who typed 21, thought better of it and typed 18 again was left with
  both buttons armed over a plan identical to the stored one. Whether anything
  changed is now derived from the diff instead of remembered in a flag that
  never came back down.

- **A backtick inside a shipped `<style>` block fails the build.** The card
  bodies are template literals, so a backtick in their CSS ends the literal and
  the card throws `SyntaxError` on import — which reaches a resident as
  "Konfigurationsfehler" and nothing else. It shipped twice in one afternoon
  before a check existed.

- **The heating log names the balancing hour.** ga_heating 0.13.0 logs a balancing
  run's changes with the source `balancing`; the log card shows it as
  "System · Einregulierung". Before, such an entry had no reason line.

- **A card the bundle stops shipping no longer stays a Lovelace resource.**
  Registration only ever added resources, and the clean-up only replaced an old
  `?v=` of a card that still ships — so a dropped card (seen: `ga-maintenance-card`
  on a 1.22.0 device, reported by ga_manager's `ga.frontend_cards` as
  `stale_registrations`) stayed registered and the panel imported a URL that
  Core answers with its HTML index. On start the integration now removes every
  resource under `/ga_frontend_bundle_first_party/` whose asset is not in this
  package, logged at WARNING. Only that path counts as ours: resident
  (`/local/…`), HACS and community-card resources are never touched, and an
  empty `first_party/` (broken package) sweeps nothing.

## 1.22.0

> **Requires ga_heating 0.12.0 or newer — ship them together.** This release
> shows −/+ on an off room, and a press there sends only
> `climate.set_temperature`. ga_heating 0.12.0 turns an OFF room on in MANUEL
> for that; on 0.11.x the radiators go to `heat` while the room stays "off", so
> the card shows AUS over a radiator that is heating, with no manual period to
> end it. The bundle has no mechanism to declare a minimum ga_heating version
> (`manifest.json` `dependencies` take no versions, and listing ga_heating there
> would stop the bundle loading on a device without it), so this is enforced
> only by pinning both in the same OS release. The change-log card also expects
> ga_heating 0.12.0's `changes` attribute; without it the card falls back to
> history, which is correct but carries no reasons.

- **The thermostat card's "Steuerung" title can be turned off.** It sits
  directly under the room's "Heizung" heading and says the same thing twice.
  New strategy option `thermostat_header`: unset keeps "Steuerung" (no fleet
  change), `""` drops the title, any other string replaces it. The card itself
  now honours `header: ""` — before, `||` turned an empty string back into
  "Steuerung", so there was no way to switch it off even by hand. Without a
  title the running-state badge ("Bereit" / "Heizt") takes its place, on the
  left, in all three variants; with neither, no empty line is left. The
  `simple` fallback gets `header: false`; `core` never had a title.
- **The mode row reads AUS · MANUEL · KI**, least heating to most, so it is one
  scale rather than three unrelated buttons. Order is presentation only: each
  button carries its own `data-mode` and the handler reads that, never a
  position, so the services called are unchanged. A test pins both.
- **An off room keeps the layout of a heating one.** It used to lose its whole
  body — no value, no −/+, just "Heizung aus" — so the card jumped every time
  someone pressed AUS. There is now ONE body for every state: the big value and
  both buttons stay exactly where they were, and the badge is the only thing that
  changes. A press on −/+ while off is a setpoint like any other, so ga_heating
  takes the room out of AUS and heats — chosen deliberately (2026-09-30), on the
  control that was already there. ("off" and "cannot be changed" are not the same
  statement, and the card must not quietly make them one.)

- **AUS is a dark neutral, not the brand colour.** Painted in the theme's primary
  like KI, "off" read as a state somebody was pleased about; `--ga-off` (default
  `#616161`) says only that the room is off.
- **The 24 h graph cards keep their title and lose Home Assistant's history link.**
  A graph card with a `title` gets a header, and inside it a chevron linking to the
  History panel filtered to those entities — `hui-history-graph-card` renders that
  `<a>` whenever a title exists, with no option to suppress it: a one-way door from a
  resident's room view into an admin-shaped page. Moving the words to a heading above
  the card took the chevron away but also took the title out of the box, so the LINK
  is what goes instead. card-mod is already injected on every GA dashboard for
  exactly this class of problem. The same rule brings that header down to 16px: it
  is an `<h1>` styled for a page title, and on a room view it shouted over the
  "Heizung" and "Verlauf" headings it sits under. The cards also carry
  `grid_options: {columns: 12, rows: 4}`, so both 24 h charts and the control above
  them fit on one screen without scrolling — sized in the sections grid's own unit
  rather than a pixel height that a different screen would get wrong.

- **The Heizplan card shows what an edit changes.** Editing a value overwrote the
  number it replaced and then asked the resident to remember it (reported
  2026-10-02). Every render now answers what the plan WILL be and what it IS, in
  three places: an edited field is marked and carries "jetzt 18 °C"; the hour's
  current setpoint is drawn as a dashed line behind the new bar on the day curve
  ("warmer or colder than now" is the real question, and two heights in one column
  answer it better than two numbers in a list); and a line names every day with
  unsaved edits, because Speichern writes the WHOLE week and the day on screen
  cannot say that. `Verwerfen` puts the week back — showing a diff without a way
  back is half the job. Rows that would disappear on save say so.
  The comparison is by POSITION, row against row: a time moved past its neighbour
  reports as two changes rather than a reorder, because the alternative guesses at
  an intent nobody expressed.
- **Plan times sit on the half hour.** `step="1800"` moves the picker, and every
  edit is snapped where it passes — a resident can still type 06:14, and a phone's
  own picker ignores `step` entirely. 23:45 rounds DOWN: rounding it up would move
  the slot to the start of the day and reorder the plan under the resident's hands.
- **An outdoor series, where a device names one.** New strategy options
  `outdoor_temperature` / `outdoor_humidity`, drawn beside the room's own curve —
  two series answer "is it cold outside or is the heating failing", which one
  cannot. The entity is NAMED, never sniffed for: guessing at `sensor.aussen*`
  breaks when somebody renames a sensor and would draw a stranger's thermometer on
  a resident's wall. A named entity that does not exist is left off the chart.
- **The log says WHO first, then why.** "Benutzer" / "System" is the question a
  resident asks of a log — was that me, or did the heating do it? A boost and a
  holiday sit on the Benutzer side: somebody asked for them, even though the system
  carried them out at a moment nobody picked. The reason is kept where it adds
  something ("System · Heizplan", "Benutzer · Boost") and dropped where it would
  restate the actor. "Manuell" is deliberately not used for the user side: MANUEL is
  a MODE on the thermostat card beside this one.

- **New: `ga-heating-log-card` — the last few changes to a room, with timestamps.**
  Asked for on 2026-09-30, and the core logbook card cannot answer it here for two
  independent reasons: a GA device loads `history:` but not `logbook:`, so
  `/api/logbook` answers 404; and even loaded, the logbook records STATE changes
  while a room's setpoint is an ATTRIBUTE — "21 → 23 °C", the thing a resident
  actually did, would never appear in it. The card reads `history/period` and
  diffs the points itself: a mode change ("KI → MANUEL") or a setpoint move
  ("Soll 21,0 → 23,0 °C"), never the measured temperature drifting a tenth, and
  one entry rather than two when AUS takes the target with it. Times read "Heute
  14:32" / "Gestern 09:15" / "Mo 07:00". "Nothing happened" and "could not read
  the history" are different sentences, because a card that renders a failed read
  as "keine Änderungen" lies about one of them.

  **It states what happened, never who did it.** History knows THAT the setpoint
  moved; only ga_heating knows whether it was the resident, the plan, a boost or
  an open window. The entries are observations for exactly that reason — the
  reason belongs in the integration, which already models it.

  Titled **"Aktivität"** — Home Assistant's own German for this: its translation
  file maps `panel.logbook` to it (HA rebuilt the Logbook as the Activity view),
  while `panel.history` is "Verlauf", already the heading over the 24 h charts.
  Taking HA's word means this card and a stock HA page never call the same thing by
  two names, which is also why the thermostat card says "Leerlauf".

  Placed under the thermostat by the strategy behind `change_log: true`, DEFAULT
  OFF while the feature is new: a card that reads the recorder on every room view
  is a cost every device would otherwise pay for something nobody has judged yet.

- **The 24 h temperature curve draws the room, not the radiator.** A TRV publishes
  its own `_local_temperature`, which is a temperature sensor in the room like any
  other — so the chart drew two curves and the legend gave no hint that the upper
  one was the valve (measured 2026-09-30: 23.65 °C at the valve against 23.40 °C
  in the room). A valve reads warm because it sits on the radiator; that is what
  `calibration.py` exists for, and it is not what a resident means by "how warm was
  it". The valves are read from the room entity's `valves` attribute and their
  sensors dropped; a room whose only thermometer IS a valve keeps it, under its own
  name, rather than showing an empty card. The remaining single curve is labelled
  "Raum Temperatur", and the card is titled "Temperatur letzte 24h".
- **The humidity curve loses its "(mean)" suffix.** Unnamed, the card labelled the
  single series "… Luftfeuchtigkeit (mean)" — the card's own arithmetic leaking
  into a resident's legend, answering a question nobody asked and reading like
  part of the sensor's name. It is named "Raum Luftfeuchtigkeit", and the card is
  titled "Luftfeuchtigkeit letzte 24h" to match the temperature one.

- **The Heizplan card ships no header.** It carried the room name, under a
  "Heizplan" heading, in a tab named after the room — the same thing three times.
  The strategy passes no `title` and the card's default is now nothing at all:
  falling back to "Heizplan" only moved the duplication one line up. A
  hand-written config that sets a `title` still gets it.

- **The temperature badge reads the sensor ga_heating named, not the thermostat.**
  An entity badge on a climate entity shows `current_temperature` and falls back to
  the ENTITY'S STATE when that attribute is missing — so a room whose thermometer
  had not reported showed its hvac mode where a temperature belongs: "Heat" beside
  a thermometer icon (seen during boot on a device 2026-10-01, and it would stay
  for as long as a sensor was offline, not only while booting). The badge now
  points at `temperature_source`, which is ga_heating's own answer to which
  thermometer is this room's — so the one-place rule still holds, and the badge has
  an entity whose state IS the temperature and reads "–" when there is none. A room
  reading its valve ("temperature_source": "valve") and an older ga_heating without
  the attribute keep the climate entity.

- **The room's temperature badge carries a thermometer.** Read off the ga_heating
  room entity, it inherited that entity's icon — the thermostat dial, which is the
  control, not the reading (seen on a device 2026-09-30). `mdi:thermometer` is now
  stated on both branches, so the badge looks the same whether the climate entity
  or a temperature sensor answers.

- **The idle badge says "Leerlauf", not "Bereit".** "Bereit" reads as standby and
  says nothing about what the heating is doing. "Leerlauf" is Home Assistant's own
  German for `hvac_action: idle`, so this card and a stock HA card never say
  different words about the same reading — and, unlike "Temperatur erreicht" or
  "Warm genug", it claims nothing about the room: a valve reports `idle` with an
  open window too.

- **The running-state badge carries an icon next to its word:** `mdi:radiator`
  for Heizt, `mdi:radiator-off` for Leerlauf, `mdi:power` for Aus (the same icon
  as the AUS mode button). The radiator pair shows the thing itself, hot or cold,
  rather than a generic flame or pause bar. The word stays — the icon reinforces it,
  it does not replace it.

## 1.21.0

- **Both Danger Zone buttons send their request again.** Since 1.9.0,
  "Nutzer entfernen" and "Endgültig löschen" in the household-management card
  did nothing: opening the dialog replaced the message line's whole `class`
  attribute, which also removed the class the card later used to find that
  line, so the click threw (`Cannot set properties of null`) before any request
  was built — and left the button disabled. The card now adds and removes only
  the `ok` / `err` state class. A new browser test opens each dialog, fills it,
  clicks, and asserts the POST (path and body) that leaves the page, including
  a second click after a failed attempt and a reopened dialog.
  A sweep of every `className =` in the first-party cards found no second
  instance: the other seven assignments keep the class they are looked up by,
  or are never looked up by class.

## 1.20.0

- **The room's measured temperature is back as a badge, before the humidity.**
  Asked for on 2026-09-25. The Heizung heading of a room view now reads
  Temperatur, Luftfeuchtigkeit, Batterie. This reverses, for the badge only, the
  2026-09-23 decision (#1060) that had dropped it; the thermostat card stays
  setpoint-only. The value comes from the room's `ga_heating` climate entity
  (`current_temperature`), which already applies the rule "room sensor first,
  valve thermometer as fallback" — one place, so badge, heating and calibration
  agree. Without a numeric reading there, the room's first temperature sensor;
  without either, no temperature badge at all, never an empty one.

## 1.19.0

- **Einstellungen carries household management, not the rooms again** (#34).
  The tab repeated every room as a stock `area` card while users, room access
  and invite links sat on a separate Verwalten tab. The master's management
  card now lives in Einstellungen and the second tab is gone; a resident who is
  not the master gets no management card.
- **An invite shows a link to send, not six digits only** (#35). The server
  has returned `invite_url` since greenautarky_site 2.9.4; the card never read
  it. The link sits in a selectable field with a "Link teilen" button (share
  sheet, clipboard fallback); the PIN stays for reading out over the phone;
  without an external URL the card says so instead of guessing a link.

## 1.18.0

- **The whole-home heating controls, on a tab called `Profil`.** Boost every
  room for five minutes, switch every room off, and a Sonderplan for sickness or
  a holiday. The card owns no heating logic: every button calls something
  `ga_heating` already had — the engine, its validation and its expiry live in
  Core, where they survive a restart a browser tab does not.

  The name is not new. The previous system had exactly this view, read in
  `ha-dashboard-automation/templates/profile_view_template.j2` on 2026-09-23,
  whose grid is literally `"boost override" / "schedule override"`. Residents of
  that system look for these controls under that word.

  It is generated only where a room entity carries a `valves` list, and never for
  a room-scoped sub-user — "alle Räume aus" must not be offered to someone who
  holds two of the flat's six rooms. The first attempt put the card in the
  household view and reached nobody: `hide_household` defaults to true, so that
  view exists on no device.

- **Four things the old Profil view had and this card did not**, all measured in
  that template rather than invented:

  - the **status is always visible** and the form collapses behind a toggle. An
    override whose status is only visible where it was entered is the invisible
    override `ga_heating`'s own source warns about;
  - **`Alle Räume` is its own switch.** "Nothing ticked = all rooms" was the
    first implementation and reads as "none";
  - the **boost shows its remaining time**, from `ga_heating` 0.10.0's new
    `override` attribute — the number the old view had from a real timer;
  - a holiday's **end carries a time**, in literal 15-minute options. The old
    source states the reason: "option text is literal, so locale-independent -
    no native 12h/AM-PM picker". Ending at 23:59 means a cold flat on the day
    the resident comes home.

  What is deliberately NOT taken is the old design's `_saved` twin for every
  field. That two-stage commit existed because its "form" was twenty live
  entities that would otherwise take effect as they were typed.

- **"Alle Räume aus" says at which temperature the valves still open**, read from
  each valve's own `frost_protection_temperature`. On a SONOFF TRVZB
  `system_mode: off` IS the anti-freeze state, while `ga_heating`'s own OFF is
  deliberately not a low setpoint — so the protection comes from the hardware and
  the card must not promise it without looking. Measured on a test device:
  7 °C, not the 5 °C the vendor documents as the default.

## 1.17.0

- **The thermostat card leads with the target, not with the measurement.** Both
  looks showed the room's current temperature — `classic` as the large number,
  `setpoint` as an "aktuell …" line above it — and put the setpoint, the one
  value a resident can act on, in a small row underneath. Asked for on
  2026-09-23: show the target only. `show_current: true` puts the measurement
  back for a diagnostic view; the default is off. The measurement itself is
  untouched — still on the entity, still drawn by the temperature/humidity view.

  The `dial` look had the same defect in a third place (`.d-cur` inside the SVG)
  and was missed by the first version of this change: it fixed the two looks a
  test drove and left the one nobody had asserted on. Found by a browser test
  against a canary, not by reading. Reachability is part of correctness.

- **The weekly plan is never an empty form.** The scheduler came back with no
  slots for a day and offered "+ Zeit hinzufügen" as the only way in, so a
  resident opening a fresh flat saw a blank week and a blank curve and had to
  invent a plan before the card could show one. Now exactly five times per day,
  always present; add and remove are gone.

  Five is not a number anyone liked: the canonical table the installation has
  used since 2026-06 (`ha-dashboard-automation`,
  `scripts/apply_default_profile_schedule.py`) has exactly five entries per day
  per room. And the padding invents nothing — a filled slot takes the
  temperature ALREADY IN FORCE at that time of day from whatever the plan
  already says, falling back only to the thermostat's own current target, which
  is a real number on the card above. A day that already carries MORE than five
  is left alone: trimming would be a silent loss of the resident's plan dressed
  up as tidying.

  Observed on a test device on 2026-09-23: the selected day went from 4 slots
  to 5, and the same browser check fails on the previous cards with
  "The plan offers 4 times for the selected day".

## 1.16.0

- **Only the community cards we actually place are injected.** All thirteen
  vendored cards rode along on every dashboard load; two are used. Measured on
  a device over the resident URL on 2026-09-22: 6.1 MB arrived before the
  browser started our own assets — plotly-graph-card 3.1 MB / 10.2 s,
  apexcharts-card 1.6 MB, mushroom 700 KB — while ga-heating-card (13 KB) only
  began downloading at 10.2 s and appeared at 11.3 s in one run and 28 s in
  another. Not one of those three is referenced anywhere in this repository or
  in `greenautarky_site`; they are named only in ga-home-strategy's own comment
  recording that HA core replaced them. The allow-list is `simple-thermostat`
  (the `simple` style's card) and `card-mod` (the style key inside it) —
  160 KB instead of 6.1 MB. The other eleven stay vendored and statically
  served, so a Lovelace resource can still load one.
- **The injected set has a byte budget**: 256 KB, deterministic, no browser and
  no network, so it can fail a pull request. Today's number is 155 KB
  (card-mod 87, simple-thermostat 62, ga-registry-guard 4, ga-sidebar-default 3).
  A wall-clock threshold on a mesh-linked device would flake and then be
  ignored; the time this buys is measured separately on a real device. The
  budget carries its own red proof — the largest vendored card alone is over
  it — because a limit that cannot be exceeded measures nothing.
- A gate reads the live sources and the live constant and compares both
  directions: a card placed but not injected is a dashboard that renders an
  error card; a card injected but not placed is this defect coming back. A
  mention in a comment does not count as a use — that distinction is why this
  went unnoticed.

## 1.12.0 — the cards actually register (2026-09-15)

**Fixed — no first-party card existed in the browser.** Measured in a real
browser on a freshly flashed canary: `customElements.get()` returned nothing for
`ga-heating-card`, `ga-thermostat-card` and `ga-master-card`, while every file
was fetched, served 200 and contained its `customElements.define(...)`. The
operator saw three separate symptoms with one cause — the heating plan card
rendering Home Assistant's red *"Custom element doesn't exist"*, the
**Verwalten** tab not loading, and the sidebar staying expanded.

*Mechanism:* the frontend's app bundle imports
`@webcomponents/scoped-custom-element-registry` on its first line, and that
polyfill replaces `window.customElements` with a new, empty registry whose
`get()` reads only its own map — so a card injected via `add_extra_js_url`, which
`index.html` starts with an inline `import()` racing that bundle, registers into
the pre-swap registry and is invisible afterwards, with nothing thrown or logged.
This is the same hazard that was already fixed for the dashboard *strategy* in an
earlier release; the note that "cards do not care, they resolve lazily" was
wrong.

*Fix:* every first-party asset is now delivered as a **Lovelace resource** — the
path the Lovelace panel loads after bootstrap — and `EARLY_INJECT_ASSET_IDS`
became an allow-list of assets that define no custom element. A card added later
is therefore delivered correctly without anyone editing a list.

**Added — `ga-registry-guard`.** Records every `ga-*` / `ll-strategy-*` element
defined against the pre-swap registry, cross-checks `window.customCards`, and
writes a `console.error` naming any element that is not in the live registry. It
defines no element itself, so it cannot be a victim of the failure it watches.
Server side, a first-party asset that cannot be delivered as a resource is now an
`ERROR` with the asset name, not a `warning` about strategies.

**Added — a headless-browser gate.** `tests/test_cards_register_in_browser.py`
drives Chromium through the load order `index.html` produces (injected modules →
the real registry-swap polyfill → Lovelace resources) and asserts every element
the shipped assets define is in the live registry. The asset list comes from
scanning `first_party/`, the element names from *running* each asset, and zero
assets or zero elements fail the run. Two fixtures pin both directions: an
element registered pre-swap must be flagged, one registered post-swap must not.

**Changed — tests that encoded the false belief.** `test_card_is_not_a_strategy`
asserted that cards keep the injection path, and `test_strategy_is_injected`
asserted an injection the code deliberately does not do. Both are replaced.
`STRATEGY_ASSET_IDS` is gone — one delivery policy, not two.
