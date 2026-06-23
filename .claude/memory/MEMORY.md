# HF Propagation App — Memory Index

- [Project overview](project_overview.md) — stack, file map, how to run
- [Propagation & antenna model](propagation_model.md) — foF2/MUF model, antenna factor (vertical/dipole/hex beam), band freqs, known limits
- [Frontend & map](frontend_map.md) — D3 Winkel Tripel, canvas heatmap, city labels, localStorage persistence, gotchas
- [API routes & external services](api_routes.md) — Flask routes (including antenna params), solar data sources, ZIP geocoding
- [UI features](ui_features.md) — panel layout, antenna section, callsign popup, help modal, overlays
- [Lambda packaging rule](feedback_lambda_packaging.md) — always rebuild lambda.zip after editing app.py, propagation.py, or templates/
