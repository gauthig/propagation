# HF Propagation App — Memory Index

- [Project overview](project_overview.md) — what the app is, stack, repo layout, venv, non-obvious infra facts
- [Roadmap & open items](project-roadmap.md) — planned "advanced antenna" release, tuner-location idea, known model gaps
- [Propagation & antenna model](propagation_model.md) — current model constants, one-reference antenna/soil design, validation evidence, pitfalls
- [API routes & services](api_routes.md) — routes incl. /antenna + auth/admin, DynamoDB (TTL history), IAM, CloudFront contract
- [Frontend & map](frontend_map.md) — layers, heat-canvas cutoff 0.12, skip circle per bearing, greyline, render gotchas
- [UI features](ui_features.md) — panel controls, antenna/soil/height UI, top-center readout, sign-in gating, localStorage
- [Lambda packaging rule](feedback_lambda_packaging.md) — bump version + rebuild after app/model/templates/antennas edits; hook & commit gotchas
- [Version scheme](project_versioning.md) — APP_VERSION YYMM.###; ### bumps each build, resets to 001 monthly
