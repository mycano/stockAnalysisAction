# Assets

README visuals, social cards, and release media.

## v5.0 investor-research visuals

| Asset | Purpose |
|---|---|
| `investor-research-architecture-en.gif` | Animated English investor-delivery architecture |
| `investor-research-architecture-zh-CN.gif` | Animated Simplified Chinese investor-delivery architecture |
| `diagrams/investor-research-architecture-*.png` | Static 1920px architecture exports |
| `diagrams/investor-research-flow-*.png` | Static evidence-first research flows |
| `diagrams/*.source.json` | Fireworks semantic source specifications |
| `diagrams/*.svg` | Validated semantic SVGs |
| `diagrams/*.layout.json` | Geometry and composition validation reports |
| `diagrams/*.motion.json` | Motion-contract validation reports |
| `demo-video-preview-en.png` | English video poster |
| `demo-video-preview-zh-CN.png` | Simplified Chinese video poster |

The architecture expresses the v5.0 investor journey:

```text
investor question
→ asset scene and investment framework
→ structured and public-web evidence
→ source/time validation
→ financial models, 15 Lenses, and risk analysis
→ evidence-backed view
→ actionable research report
```

All diagram sources were rendered with the `fireworks-tech-graph` skill. Static
exports preserve CJK text through browser-native SVG rendering; animated
architecture files use the validated `agent-orchestration` motion contract.

## Demo video

Editable Remotion source lives in [`../promo/demo-video`](../promo/demo-video/).
Final 1080p outputs:

- `../promo/demo-video/out/stock-analysis-demo-en.mp4`
- `../promo/demo-video/out/stock-analysis-demo-zh-CN.mp4`

## Legacy screenshots and share cards

- `social-preview.png`: GitHub repository social preview.
- `share-cn-1.png`: Chinese social card.
- `share-x-1.png`, `share-x-2.png`: short-form social cards.
- Existing market, stock-Lens, and fund screenshot sets remain for historical
  examples; the v5.0 README uses the architecture, flow, and video assets above.
