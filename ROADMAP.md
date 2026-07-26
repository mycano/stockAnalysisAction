# Roadmap

v5.0 establishes `stock-analysis` as an investor-facing research system:
scene-specific report contracts, an independent 15-Lens path, built-in public
evidence acquisition, deterministic derivations, and a strict delivery boundary
between private audit artifacts and the report.

## Near term

- Expand first-party filing connectors for A/HK/US/JP/KR without weakening
  source and effective-date rules.
- Add more real-business acceptance fixtures for active funds, cross-border
  ETFs, portfolio stress, and screening universes.
- Improve fund attribution and ETF tracking-quality evidence.
- Add compact, publishable example reports that pass the investor-facing lint.
- Keep README visuals, bilingual videos, package metadata, and generated Agent
  entrypoints synchronized with every release.

## Research quality

- Strengthen peer selection and historical comparability checks.
- Expand reproducible valuation derivations and sensitivity validation.
- Add more Lens-specific evidence requirements, especially governance,
  channel, innovation, market-positioning, and transaction-cost evidence.
- Measure claim usefulness and decision value, not report length or Agent count.
- Continue reducing boilerplate while preserving risk and falsification signals.

## Evidence coverage

- Prefer regulator, exchange, issuer, fund-company, and index-provider sources
  for critical facts.
- Add deterministic conflict resolution for more structured and web sources.
- Improve PDF table extraction and source-location capture.
- Preserve silent provider fallback; do not turn tool installation into a user
  prerequisite.

## Delivery

- Add investor-facing snapshot tests for every command and report scene.
- Extend Chinese/English semantic translation for financial metrics.
- Keep internal JSON, raw field names, paths, and provider errors out of the
  default interface.
- Keep material data-boundary notices short and outside the report body.

## Out of scope

- Broker order placement or auto-trading.
- Private-account scraping.
- Fabricating missing financial facts with model inference.
- Personalized absolute position sizing without holdings and risk context.
- Publishing internal audit objects as the investor experience.
