# Roadmap

`stock-analysis` is available as a CLI, Python package, and generated Agent entrypoints. The next milestone is broadening primary-evidence coverage without weakening its deterministic research contracts.

## Near Term

- Keep the PyPI package, console script, `--help`, Agent entrypoints, and first-run examples in sync.
- Keep README screenshots current with real generated output.
- Add more compact example reports under `reports/`.
- Improve `diagnose` output so source failures are easy to attach to issues.
- Add compact examples for auditing the Research Workspace claim ledger.

## Data Quality

- Expand deterministic tests for quote parsing, symbol normalization, and evidence scoring.
- Add source-specific fixtures for Tencent, Sina, Eastmoney, Tiantian Fund, and Futu public data.
- Improve metadata for fallback events, rate limiting, and browser handoff.
- Keep missing fields visible rather than backfilling them with misleading defaults.

## Market Coverage

- Strengthen A-share board, fund-flow, risk-calendar, and financial snapshot coverage.
- Continue hardening HK/US/JP/KR quote fallback and historical K-line consistency.
- Add more fund profile fields where public routes are stable.
- Document region-specific limitations before expanding new markets.

## Agent Workflows

- Keep the GitHub Actions daily recap example aligned with the current Evidence Pack contract.
- Add a cron example for local market notes.
- Consider MCP only after the CLI and evidence contract are stable.

### Future Roadmap (post-v4.17)

The following four items were intentionally moved out of the v4.17 P0/P1 release so it stays focused on the command protocol, multi-host compatibility, and deterministic routing:

- Add dedicated Hermes adapters on top of the stable HostRequest protocol.
- Add host-side Web/PDF enrichment without moving evidence mutation into the Python Router.
- Add opt-in anonymous telemetry; it must remain disabled by default.
- Use real, explicitly collected routing failures to optimize route selection without weakening deterministic rules.

## Community

- Keep issue templates focused on data-source failures, feature requests, lens requests, and docs/examples.
- Submit small, well-targeted PRs to finance and AI-agent Awesome Lists.
- Keep social previews, architecture GIFs, and bilingual demo videos aligned with each feature release.

## Out of Scope

- Broker order placement.
- Auto-trading.
- Private account scraping.
- Unverifiable LLM-only recommendations.
- Hiding data-source failures in polished prose.
