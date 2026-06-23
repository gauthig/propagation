---
name: ui-features
description: "Panel layout, antenna controls, session tracking, JS helpers, modals, overlays, and persistence"
metadata: 
  node_type: memory
  type: project
  originSessionId: 01d8b071-b683-4806-9b45-7401f7b7e97b
---

## Panel layout

Dark glass-morphism panel (top-left, fixed, scrollable, max-height 100vh).

**Header** (sticky):
- "HF PROPAGATION" title
- Callsign badge below title — shows stored callsign, click to re-open callsign popup
- `?` help button → Help/About modal
- `☰` / `✕` hamburger — toggles `#panel-body.collapsed`

**Panel body** (collapsible):

1. **Band dropdown** — 7 bands (80m → 10m), default 20m

2. **Antenna section**:
   - "Use Antenna" checkbox (`#ant-enable`) — **unchecked by default**; greys out controls when off
   - Type: Vertical | Dipole | Hex Beam
   - Height (10–100 ft) — hidden when Vertical selected
   - Hex Beam: azimuth input; error shown if band is 80m/60m/40m
   - Dipole: wire orientation select (N-S, NE-SW, E-W, NW-SE)

3. **Solar Indices** — 2×2 cards (Solar Flux, K-Index, A-Index, Sunspots) with hover tooltips

4. **Band Conditions table** — Good/Fair/Poor pills, day/night, from hamqsl.com

5. **Refresh Now button** — **only visible when callsign is WB0Z**; calls `POST /solar/refresh` with `{callsign: "WB0Z"}` in the body

6. **My QTH** section — Grid | Lat/Lon | ZIP tabs

## Session tracking (localStorage + DynamoDB)

localStorage keys:
- `hf_session_id` — UUID generated on first visit via `crypto.randomUUID()`, persists across sessions; sent with `/track/callsign` as a reference attribute (not the DynamoDB PK)
- `hf_callsign` — stored callsign; **this is the DynamoDB primary key** for `hf_users`
- `hf_qth_lat`, `hf_qth_lon`, `hf_qth_label` — last-set QTH

**Callsign is the stable identity.** The same `hf_users` row is updated no matter which browser, IP address, or device the user connects from — as long as they enter the same callsign. Anonymous visitors (skipped callsign) are not written to DynamoDB.

On every page load:
1. `initSession()` — restores callsign + QTH from localStorage; if callsign is stored, calls `trackCallsign()` to re-link current session to the callsign row in DynamoDB
2. `trackVisit()` — POSTs `{callsign}` to `/track/visit`; increments `access_count` in `hf_users`

On callsign save: `trackCallsign(callsign)` → POST `/track/callsign` with `{callsign, session_id}`
On QTH set: `trackQTH(lat, lon, method)` → POST `/track/qth` with `{callsign, lat, lon, method}`

## JS tracking helpers

```javascript
function _postTrack(path, payload) {
  fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: getSessionId(), ...payload}),
  }).catch(() => {});
}

function trackVisit() {
  const callsign = (localStorage.getItem(LS_CALL) || '').toUpperCase();
  _postTrack('/track/visit', {callsign});
}
function trackCallsign(callsign)    { _postTrack('/track/callsign', {callsign}); }
function trackQTH(lat, lon, method) {
  const callsign = (localStorage.getItem(LS_CALL) || '').toUpperCase();
  _postTrack('/track/qth', {callsign, lat, lon, method});
}
```

All three are fire-and-forget (`.catch(() => {})`). `_postTrack` is the single fetch wrapper — add headers/retries there.

## Refresh button visibility rule
```javascript
function updateRefreshBtn() {
  const callsign = (localStorage.getItem('hf_callsign') || '').toUpperCase();
  document.getElementById('refresh-btn').style.display = callsign === 'WB0Z' ? '' : 'none';
}
```
Called from `applyCallsign()` on every callsign change and page load.

`manualRefresh()` POSTs `{callsign}` to `/solar/refresh` so the history row records who triggered the refresh.

## Modals

**Callsign popup** — shown 800 ms after first visit (when `localStorage['hf_callsign'] === null`). "Skip" saves empty string. Clicking the badge re-opens it.

**Help/About modal** — propagation model, antenna model, solar sources, color scale explanation.

## Map overlays

- QTH dot — 7px cyan circle with SVG glow filter
- Skip zone — gray dashed ring from `estimateSkipKm(freq, sfi)`
- City labels — ~46 major cities, double-rendered for dark background
- Heatmap — canvas layer with `blur(9px)` CSS filter, alpha-capped at 57% to keep map visible
