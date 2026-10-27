# Charts in Iris

Source components installed from [Bklit UI](https://bklit.com/docs/installation)
on 2026-10-27 with:

```powershell
npx shadcn@latest add @bklit/area-chart @bklit/pie-chart @bklit/y-axis --yes
```

Registry dependencies include the grid, axes, tooltip, interaction context,
responsive container and series helpers. `components.json` configures `@bklit`
and the `@/` alias. The original chart components are MIT licensed; see
`LICENSE.bklit.txt`.

Iris adaptations:

- `anime-runtime.tsx` runs chart reveals, path changes, hover and tooltip motion
  through the existing Anime.js v4 runtime, with cleanup and reduced motion.
  `motion` is a development dependency for the upstream prop declarations only;
  there are no runtime imports of its animation engine.
- `chart-stat-flow.tsx` uses `ExpenseNumber` in place of NumberFlow.
- `chart-formatters.ts` uses Russian number and date formats. The activity chart
  uses the interval labels supplied by the backend.
- Single-finger inspection does not cancel native vertical scrolling; the
  activity chart allows `pan-y` on touch screens.
- Vite does not need the registry's Next.js `use client` directives.
- `bklit.css` generates chart utilities without Tailwind preflight or a global
  palette. All colours are scoped to `.iris-charts` and reference `tokens.css`.
  Iris currently has one dark theme.
- `ExpenseDashboard.css` owns the settings composition and disables the
  registry's CSS transitions. Native Iris components own the controls.

`TokenUsageChart` composes the area chart, grid, axes and tooltip. Tokens and
requests can be viewed by interval or cumulatively. Cached tokens remain a
subset of input tokens. A custom keyboard explorer writes to Bklit's hover
context, so pointer, touch and keyboard use the same tooltip data.

`TokenBreakdownChart` composes a donut with a linked, keyboard-accessible legend.
Purpose rows open the existing journal filtered by purpose. The journal API
returns records across all periods; chart period selection applies to summary
statistics and distributions.

When reinstalling registry components, review these adaptations before replacing
the local source. The adapter covers the primitives used by these installed
charts; new Bklit animation features may need an explicit Anime.js adaptation.
