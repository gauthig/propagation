---
name: ui-features
description: "Panel controls, antenna/soil UI, top-center readout, sign-in gating, localStorage keys and UI gotchas"
metadata:
  node_type: memory
  type: project
  originSessionId: 01d8b071-b683-4806-9b45-7401f7b7e97b
  modified: 2026-09-27T18:07:43.933Z
---

## Top-center
`#band-display`: band name + ☰ band-plan toggle; band plan starts **hidden** (`bp-collapsed`).
Under it, `#antenna-readout` (own line so long text can't push the header under the side panel):
antenna · height · soil (σ from the dropdown label) · dB @10°/20° from `/antenna/<band>`
(`updateAntennaReadout`, sequence-guarded against late replies). Unticked → "No antenna model".

## Side panel (collapsible `#panel-body`)
1. Band select (8 bands, boots on 40m — or 20m if a saved hex beam is active) + **Show greyline**
   (`hf_show_greyline`; not login-locked).
2. Antenna — "Use antenna" (`#ant-enable`, off by default) dims but doesn't lock; touching any
   antenna control auto-ticks it (pre-2609.002 changes were silently ignored).
   - Types: Vertical (true λ/4, no height) | Dipole | Hex Beam (20–10m only) | Elevated GP
     (Zero Five 10–80m, `egp_zf80`).
   - Height on its own row (long type names once pushed it off the panel; `.ant-select{min-width:0}`).
     `setHeightOptions()` swaps lists: 10–100 ft "Height from Ground" vs 4–12 ft "Base Height"
     (default 8); each list's value remembered (`hf_antenna.height` / `.height_egp`).
   - Soil `#ant-soil`, 5 choices with S/m in the label, shown for every antenna type.
   - Hex azimuth applies 400 ms after typing stops; dipole wire orientation N-S/NE-SW/E-W/NW-SE.
3. Solar indices cards, band-conditions table (hamqsl), WB0Z-only "Refresh Now" (POST /solar/refresh).
4. My QTH — Grid | Lat/Lon | ZIP.
Not signed in → QTH + antenna controls are locked (`panel-locked`); band and greyline stay usable.
Sign-in badge opens login/register (email reset via SES); admins get a user-management panel.

## localStorage
`hf_qth_lat/lon/label`, `hf_antenna` {enabled, type, height, height_egp, azimuth, orient, soil},
`hf_show_greyline`, `hf_session_id`, `hf_callsign`. Auth itself is the `hf_auth` cookie.
All reads/writes wrapped in try/catch.

## Help modal
Sections: What it does, Open Source (GPL-3.0, github.com/gauthig/propagation), Propagation
Model, Antenna Model (vertical = λ/4 reference, soil, dipole height, readout), Solar Data
Sources, Color Scale, Skip Zone, privacy/data sections. Keep it in sync with model changes.

See [[frontend-map]] for drawing, [[api-routes]] for the endpoints.
