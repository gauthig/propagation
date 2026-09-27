---
name: project-roadmap
description: "Open ideas, planned releases and known model gaps for the propagation app (as of 2026-09-27)"
metadata:
  node_type: memory
  type: project
  originSessionId: 431d76a1-ebb1-4f7b-acf0-4154ae098a91
  modified: 2026-09-27T18:06:37.727Z
---

State 2026-09-27: v2609.008 live. Items below were raised with the user but not built.

**Planned by the user**
- "Advanced antenna features" release — let users describe/tune their own setup (radials, feed,
  tuner…). User deferred it on 2026-09-27 until after 2609.007.
- Possible "tuner location" option: a remote tuner at the feedpoint would cut the Zero Five's 80m
  coax loss from ~7 dB to <1 dB. User asked whether a radio-side SWR box mattered — it doesn't
  (shack tuner leaves coax SWR unchanged; radio-side mismatch ≤0.2 dB at 1.5:1). Rejected that idea.

**Known model gaps (evidence-based)**
- No long multi-hop path loss → Pacific/South-Pacific paths brighter than WSPR hearing supports.
- Dipole/hex absolute level vs the vertical is still the old 1.30 heuristic, not NEC gain.
- Calibration is one equinox week at SFI 101–121, Kp ≤4.3, one QTH — re-run `tools/validate/` in
  winter/summer, at high SFI and in a storm before trusting constants there.
- Asia from SoCal: too few WSPR hearings (~19/week) to judge.
- VOACAP comparison never run — needs installing ITS HF (Windows) or voacapl; ask first.

**Good next validation**
- User runs WSPR on the Zero Five with their own callsign → compare their spots vs other SoCal
  stations with `tools/validate/wspr.py` (real A/B for the NEC antenna table).

Related: [[propagation-model]], [[user-profile]].
