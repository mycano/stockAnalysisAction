# stock-analysis bilingual demo

Editable 72-second, 1920×1080 Remotion introduction for v5.0.

The English and Simplified Chinese cuts show the same investor journey:

```text
plain-language question
→ scene or explicit investment framework
→ built-in public evidence
→ source/time validation and reproducible derivation
→ valuation, risks, catalysts, and action conditions
→ actionable research report
```

The video makes three v5.0 promises explicit:

- evidence is verified before a view is formed;
- stocks, funds, markets, earnings, price moves, and portfolios use scene-specific research;
- the 15 expert frameworks are distinct research protocols, not writing styles.

```bash
npm install
npm run check
npm run studio
npm run still
npm run render
```

- Compositions: `StockAnalysisDemo` (English), `StockAnalysisDemoZh` (简体中文)
- Frame rate: 30 fps
- Final outputs:
  - `out/stock-analysis-demo-en.mp4`
  - `out/stock-analysis-demo-zh-CN.mp4`
- Preview stills:
  - `../../assets/demo-video-preview-en.png`
  - `../../assets/demo-video-preview-zh-CN.png`

The composition uses captions instead of voiceover or music, so it remains
usable in muted feeds and is localized entirely in `src/video.jsx`.
