# HF Propagation App — Memory Index

- [Project overview](project_overview.md) — stack, file map, how to run
- [Propagation & antenna model](propagation_model.md) — foF2/MUF model (reworked 2026-09 — zenith-driven foF2, curved-earth hops, D-layer absorption, tuning notes), antenna factor, skip circle, known limits
- [Frontend & map](frontend_map.md) — D3 Winkel Tripel, canvas heatmap, city labels, localStorage persistence, gotchas
- [API routes & external services](api_routes.md) — Flask routes (including antenna params), solar data sources, ZIP geocoding
- [UI features](ui_features.md) — panel layout, antenna section, callsign popup, help modal, overlays
- [Lambda packaging rule](feedback_lambda_packaging.md) — always rebuild lambda.zip after editing app.py, propagation.py, or templates/
- [OneDrive lock handling](feedback-onedrive-lock.md) — on build file-lock errors, wait 30s for sync and retry (don't reroute the build)
- [Skipped optimizations](optimizations-skipped.md) — propagation loop micro-opt & index.html minify were declined; don't re-raise
- [Version scheme](project_versioning.md) — APP_VERSION format YYMM.###; ### bumps each build and resets to 001 at each new month
