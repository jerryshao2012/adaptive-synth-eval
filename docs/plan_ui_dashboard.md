# AI Evaluation Continuous Monitoring Dashboard — Implementation Plan

## 1. Overview

A BMO-styled web dashboard for continuous monitoring of AI evaluation metrics. Dark mode is the default (matching monitoring use cases), with light mode support via OS `prefers-color-scheme`. This is a **frontend-only webapp** — it consumes evaluation data from a backend API that reads from the adaptive-synth-eval output artifacts (`conversations.jsonl`). The backend also handles batch AI evaluation to generate eval metrics on demand, using a **metric version control system** derived from the AI Eval Framework (`ai_eval_framework/service/functions/Evals`).

Key design influences:
- **BMO DeepAgent UI** (`bmo-deepagent-ui`): Dark navy theme, Geist typography, shadcn/ui components, CSS variable token system, resizable panel layout
- **AI Eval Framework** (`ai_eval_framework`): Batch evaluation architecture, metric versioning (`MetricValueVersioned`), threshold configuration, Cosmos DB-backed persistence, cron-based scheduling
- **eval_engine.py** (`voice/assistant/eval_engine.py`): The 10 real-time evaluation metrics (toxicity, bias, relevance, groundedness, correctness, completeness, style, robustness, compliance, precision) plus system reliability

The dashboard displays historical evaluation data with per-chart configurable time windows, metric version tracking, and threshold-aware visualizations.

---

## 2. Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | Next.js 16 (App Router) | Matches BMO stack; RSC for data, client components for charts |
| Language | TypeScript (strict) | Matches BMO |
| Styling | Tailwind CSS v3.4 + `tailwindcss-animate` | Matches BMO |
| Component System | shadcn/ui (base: `slate`, `cssVariables: true`) | Matches BMO; `button`, `card`, `select`, `tabs`, `tooltip`, `dialog`, `skeleton`, `scroll-area`, `badge` |
| Icons | Lucide React | Matches BMO |
| Charts | **Recharts** (not Chart.js) | React-native, composable, shadcn/ui-compatible, good for dashboards with responsive containers and built-in tooltip/legend/zoom support |
| Fonts | Geist Sans + Geist Mono | Matches BMO exactly |
| Utilities | `clsx` + `tailwind-merge` (`cn()`), `class-variance-authority` | Matches BMO |
| Date handling | `date-fns` | Lightweight, tree-shakeable, good for time-range math |
| Data fetching | `fetch` + React Query (`@tanstack/react-query`) | Caching, refetch intervals, loading/error states |
| Dynamic imports | `next/dynamic` | Code-split heavy chart components |

---

## 3. Design System (BMO-Adopted)

### 3.1 Colors (Dark-default with light mode, identical to BMO)

**Dark mode (`:root` defaults):**

```
--color-primary:        #1155cc    (brand blue)
--color-secondary:      #51a3d5    (accent blue)
--color-success:        #2fbf71    (pass state)
--color-warning:        #ffb73c    (warn state)
--color-error:          #ee0000    (fail state)
--color-background:     #030a12    (page bg)
--color-surface:        #141a22    (card bg)
--color-border:         #2c394c    (borders)
--color-border-light:   #1e2a3a    (subtle borders)
--color-text-primary:   #eaf1ff    (headings)
--color-text-secondary: #b7c4d6    (body)
--color-text-tertiary:  #8fa0b6    (captions)
--color-header-bg:      #102e40    (top bar)
```

**Metric status colors (chart lines & badges):**
- `pass` → `#2fbf71` (green)
- `warn` → `#ffb73c` (amber)
- `fail` → `#ee0000` (red)

**Chart palette (from BMO's chart-[1-5] tokens):**
- chart-1: `hsl(12, 76%, 61%)` — salmon (toxicity, bias)
- chart-2: `hsl(173, 58%, 39%)` — teal (groundedness, relevance)
- chart-3: `hsl(197, 37%, 24%)` — dark blue
- chart-4: `hsl(43, 74%, 66%)` — gold (style, correctness)
- chart-5: `hsl(27, 87%, 67%)` — orange

**Light mode (`@media (prefers-color-scheme: light)` overrides):**

| Token | Dark | Light |
|-------|------|-------|
| `--color-background` | `#030a12` | `#f5f7fb` |
| `--color-surface` | `#141a22` | `#ffffff` |
| `--color-border` | `#2c394c` | `#d5dee9` |
| `--color-border-light` | `#1e2a3a` | `#e3eaf3` |
| `--color-text-primary` | `#eaf1ff` | `#0f1f33` |
| `--color-text-secondary` | `#b7c4d6` | `#344a63` |
| `--color-text-tertiary` | `#8fa0b6` | `#6c839f` |
| `--color-header-bg` | `#102e40` | `#ffffff` |
| `--color-user-message-bg` | `#1a2230` | `#e8eef7` |

The brand primary (`#1155cc`) is identical across both modes. All CSS variables swap seamlessly via the media query — no manual toggle needed.

### 3.2 Typography (identical to BMO)

```css
--font-family-base: "Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
--font-family-mono: "Geist Mono", "Fira Code", ui-monospace, monospace;
```

Type scale: `text-xxs` (12px) → `text-xs` (13px) → `text-sm` (14px) → `text-base` (16px) → `text-lg` (18px) → `text-xl` (20px) → `.display-sm` (16px/600) → `.display-base` (24px) → `.display-lg` (30px) → `.display-xl` (36px) → `.display-2xl` (48px)

### 3.3 Spacing (8px rhythm)

Tailwind spacing scale: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64

### 3.4 Border Radius

`--radius: 0.5rem` (shadcn default), cards use `rounded-lg`, buttons use `rounded-md`

### 3.5 Shadows & Effects

- Cards: `border border-border` on dark bg, no heavy shadow
- Hover: lifts via `color-mix(in srgb, var(--color-primary) 4%, transparent)` background + border tint
- Focus: `ring-2 ring-ring ring-offset-2 ring-offset-background`

---

## 4. Page Layout

```
┌──────────────────────────────────────────────────────────┐
│  Header Bar (h-16, border-b, --color-header-bg)          │
│  ┌─────┐                                    ┌──────────┐ │
│  │Logo │ AI Eval Monitor          [Refresh] [Settings]  │ │
│  └─────┘                                    └──────────┘ │
├──────────────────────────────────────────────────────────┤
│  Global Time Range: [This Week ▼]  Last updated: 2m ago  │
│                                                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────┐ │
│  │ Total Eval │ │  Pass Rate │ │  Fail Rate │ │ Avg   │ │
│  │   1,247    │ │    87%     │ │    3.2%    │ │ Score │ │
│  │  ↑12% vs   │ │  ↑2% vs   │ │  ↓1% vs   │ │  82/100│ │
│  │  last wk   │ │  last wk   │ │  last wk   │ │        │ │
│  └────────────┘ └────────────┘ └────────────┘ └───────┘ │
│                                                          │
│  ┌─ Tabs ─────────────────────────────────────────────┐ │
│  │ [Safety Metrics] [Performance Metrics] [Reliability] │ │
│  ├─────────────────────────────────────────────────────┤ │
│  │                                                     │ │
│  │  ┌── Chart Card (col-span-2) ────────────────────┐  │ │
│  │  │ Toxicity Score Over Time    [This Month ▼]    │  │ │
│  │  │ ┌─────────────────────────────────────────┐   │  │ │
│  │  │ │     ╱╲    ___                           │   │  │ │
│  │  │ │  __╱  ╲__╱   ╲___     (line chart)     │   │  │ │
│  │  │ │          ╲        ╲___                  │   │  │ │
│  │  │ │  0.65 ───────────────── fail threshold  │   │  │ │
│  │  │ │  0.85 ───────────────── warn threshold  │   │  │ │
│  │  │ └─────────────────────────────────────────┘   │  │ │
│  │  │  Avg: 0.89  Min: 0.62  Max: 0.98             │  │ │
│  │  └──────────────────────────────────────────────┘  │ │
│  │                                                     │ │
│  │  ┌── Chart Card ───┐ ┌── Chart Card ────────────┐  │ │
│  │  │ Bias & Fairness  │ │ Robustness Score         │  │ │
│  │  │ [This Week ▼]   │ │ [This Month ▼]           │  │ │
│  │  │ [line chart]     │ │ [line chart]              │  │ │
│  │  └─────────────────┘ └──────────────────────────┘  │ │
│  │                                                     │ │
│  │  ┌── Chart Card ───┐ ┌── Chart Card ────────────┐  │ │
│  │  │ Compliance       │ │ [empty if < 4 metrics]   │  │ │
│  │  │ [This Quarter ▼]│ │                          │  │ │
│  │  └─────────────────┘ └──────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 4.1 Layout Principles

- **Max-width**: `1280px` content container, centered (slightly wider than BMO chat 1024px since dashboards need more horizontal space)
- **Chart grid**: `grid-cols-2` at ≥1024px, `grid-cols-1` at <1024px
- **Sticky header**: The global time range bar stays sticky below the main header
- **Tabs**: shadcn Tabs component for Safety / Performance / Reliability sections
- **KPI row**: 4 stat cards in a `grid-cols-4` (≥1024px) → `grid-cols-2` (<1024px) → `grid-cols-1` (<640px)

---

## 5. Component Tree

```
app/layout.tsx
├── ThemeProvider (dark-default, follows OS prefers-color-scheme for light mode)
├── QueryClientProvider (React Query)
└── app/page.tsx (DashboardPage)
    ├── DashboardHeader
    │   ├── Logo + Title
    │   ├── LastUpdatedBadge
    │   └── ActionButtons (Refresh, Settings)
    ├── GlobalTimeRangeBar
    │   ├── TimeRangeSelector (shared default)
    │   └── AutoRefreshToggle
    ├── KpiSummaryRow
    │   └── KpiCard × 4
    │       ├── MetricValue (large number)
    │       ├── TrendIndicator (↑/↓ + % change)
    │       └── Sparkline (mini area chart, optional)
    └── MetricsTabs
        ├── Tab: Safety
        │   ├── ChartCard (toxicity, col-span-2 for primary)
        │   ├── ChartCard (bias_fairness)
        │   ├── ChartCard (robustness)
        │   └── ChartCard (compliance)
        ├── Tab: Performance
        │   ├── ChartCard (relevance, col-span-2)
        │   ├── ChartCard (groundedness)
        │   ├── ChartCard (correctness)
        │   ├── ChartCard (completeness)
        │   ├── ChartCard (style)
        │   └── ChartCard (precision)
        └── Tab: Reliability
            ├── ChartCard (total_latency_ms, col-span-2)
            ├── ChartCard (llm_latency_ms)
            ├── ChartCard (guardrail_latency_ms)
            └── ChartCard (availability)
```

### Reusable Components

**`ChartCard`** — The core building block:
```
ChartCard
├── CardHeader
│   ├── MetricLabel (name + info tooltip)
│   ├── VersionBadge (if multiple versions: "v1.0" pill, clickable to switch/compare)
│   ├── CurrentValue (latest score badge: pass/warn/fail color)
│   └── TimePeriodSelector (per-chart override)
├── CardContent
│   ├── MetricLineChart (Recharts)
│   │   ├── ReferenceLine (warn threshold)
│   │   ├── ReferenceLine (fail threshold)
│   │   ├── Multiple Line series if version-overlay mode
│   │   └── Tooltip (hover: date, score, status, detail, version)
│   └── ChartSummaryBar
│       ├── AvgScore
│       ├── MinScore
│       └── MaxScore
└── CardFooter (optional)
    └── ViewDetailsButton → DetailDialog
```

**`TimePeriodSelector`** — Dropdown or segmented control:
```
TimePeriodSelector
├── PresetButton: "This Week"
├── PresetButton: "This Month"
├── PresetButton: "This Quarter"
├── PresetButton: "Last 7 Days"
├── PresetButton: "Last 30 Days"
└── CustomRange → DateRangePicker (future)
```

**`MetricLineChart`** — The Recharts wrapper:
```
MetricLineChart
├── ResponsiveContainer
│   └── LineChart
│       ├── CartesianGrid (subtle, stroke=--color-border-light)
│       ├── XAxis (time, formatted via date-fns)
│       ├── YAxis (0-100%, domain [0, 100])
│       ├── ReferenceLine (warn threshold, stroke=--color-warning, dashed)
│       ├── ReferenceLine (fail threshold, stroke=--color-error, dashed)
│       ├── Line (score %, stroke=--color-primary, dot=r=3)
│       ├── Tooltip (custom, dark-themed)
│       └── Brush (optional, for zoom/pan)
```

**`DetailDialog`** — Full trace inspection:
```
DetailDialog (shadcn Dialog)
├── DialogHeader: metric name + version badge + timestamp
├── DialogContent
│   ├── Score gauge
│   ├── Status badge
│   ├── Metric version (policy_version from metadata)
│   ├── Detail text
│   ├── Reason
│   ├── User text (truncated)
│   ├── Response text (truncated)
│   └── Trace info (judge model, prompt version, processing time, value_object_type)
```

---

## 6. Data Model & API Contract

### 6.1 Data Model with Metric Version Control

Following the AI Eval Framework's versioning design (`MetricValueVersioned`), every metric carries its own `version` field and metadata:

```json
{
  "metric_name": "safety_toxicity",
  "value": 0.98,
  "version": "1.0",
  "timestamp": "2026-07-08T14:32:00Z",
  "metric_type": "safety",
  "metadata": {
    "policy_version": "1.0",
    "value_object_version": "1.0",
    "value_object_type": "metric_value_versioned"
  }
}
```

**Why versioning matters for the dashboard:**
- When the evaluation algorithm changes (e.g., toxity scoring bumps from v1.0 to v2.0), old and new scores can coexist without overwriting.
- Charts can display a **version selector** to filter by metric version or overlay v1.0 vs v2.0 for comparison.
- The detail dialog shows which policy version produced each score for full traceability.

### 6.2 API Endpoints (backend provides these)

**Primary data endpoint:**
```
GET /api/evaluations/history?from=2026-07-01T00:00:00Z&to=2026-07-08T23:59:59Z&limit=2000
```

**Optional batch eval status endpoint:**
```
GET /api/evaluations/status
→ { "running": true, "progress": { "completed": 450, "total": 1200 }, "started_at": "..." }
```
The dashboard uses this to show a subtle "Batch eval running…" indicator in the header bar, so users know new data is incoming.

**Response:**
```json
{
  "evaluations": [
    {
      "timestamp": "2026-07-08T14:32:00Z",
      "turn_id": "abc12345",
      "user_text": "What's my balance?",
      "response_text": "Your current balance is $1,250.00...",
      "variant": "delivered",
      "safety_status": "pass",
      "performance_status": "pass",
      "safety_metrics": {
        "toxicity": { "score": 0.98, "percent": 98, "status": "pass", "detail": "..." },
        "bias_fairness": { "score": 0.92, "percent": 92, "status": "pass", "detail": "..." },
        "robustness": { "score": 0.95, "percent": 95, "status": "pass", "detail": "..." },
        "compliance": { "score": 0.88, "percent": 88, "status": "pass", "detail": "..." }
      },
      "performance_metrics": {
        "relevance": { "score": 0.85, "percent": 85, "status": "pass", "detail": "..." },
        "groundedness": { "score": 0.78, "percent": 78, "status": "warn", "detail": "..." },
        "correctness": { "score": 0.72, "percent": 72, "status": "pass", "detail": "..." },
        "completeness": { "score": 0.65, "percent": 65, "status": "pass", "detail": "..." },
        "style": { "score": 0.60, "percent": 60, "status": "warn", "detail": "..." },
        "precision": { "score": 0.82, "percent": 82, "status": "pass", "detail": "..." }
      },
      "system_reliability": {
        "llm_latency_ms": 1200,
        "llm_latency_status": "pass",
        "guardrail_latency_ms": 350,
        "guardrail_latency_status": "pass",
        "total_latency_ms": 1550,
        "total_latency_status": "pass",
        "availability": 1.0,
        "availability_status": "pass"
      }
    }
  ],
  "total": 1247,
  "from": "2026-07-01T00:00:00Z",
  "to": "2026-07-08T23:59:59Z"
}
```

### 6.2 Frontend Data Flow

```
API Response
  │
  ├── useEvaluationsQuery(from, to)   ← React Query
  │     │
  │     ├── data → KpiSummaryRow (aggregate in useMemo)
  │     │         ├── totalEvaluations
  │     │         ├── passRate  (% of safety=pass AND performance=pass)
  │     │         ├── failRate  (% of either safety=fail OR performance=fail)
  │     │         └── avgScore  (mean of all 10 metric percents)
  │     │
  │     ├── data → ChartCard (filter + sort by timestamp)
  │     │         ├── Extract metric time-series
  │     │         ├── Compute avg/min/max
  │     │         └── Pass to MetricLineChart
  │     │
  │     └── states → Loading (Skeleton grid), Error (ErrorCard), Empty (EmptyState)
  │
  └── Per-chart TimePeriodSelector
        └── Triggers useQuery refetch with updated from/to params
```

### 6.3 Time Period Presets (computed client-side)

```typescript
const TIME_PERIODS = {
  'this-week':     { from: startOfWeek(now),  to: now },
  'this-month':    { from: startOfMonth(now), to: now },
  'this-quarter':  { from: startOfQuarter(now), to: now },
  'last-7-days':   { from: subDays(now, 7),   to: now },
  'last-30-days':  { from: subDays(now, 30),  to: now },
  'last-90-days':  { from: subDays(now, 90),  to: now },
} as const;
```

Each chart can independently set its own time period. A "Use Global" default links to the global selector.

---

## 7. Chart Configuration Per Metric

| Tab | Metric | Chart Type | Threshold Lines | Y-Axis | Span |
|-----|--------|-----------|-----------------|--------|------|
| Safety | Toxicity | Line | warn=85, fail=65 | 0–100% | full |
| Safety | Bias & Fairness | Line | warn=85, fail=65 | 0–100% | half |
| Safety | Robustness | Line | warn=90, fail=75 | 0–100% | half |
| Safety | Compliance | Line | warn=90, fail=75 | 0–100% | half |
| Perf | Relevance | Line | warn=85, fail=60 | 0–100% | full |
| Perf | Groundedness | Line | warn=80, fail=55 | 0–100% | half |
| Perf | Correctness | Line | warn=65, fail=40 | 0–100% | half |
| Perf | Completeness | Line | warn=65, fail=40 | 0–100% | half |
| Perf | Style | Line | warn=70, fail=45 | 0–100% | half |
| Perf | Precision | Line | warn=75, fail=50 | 0–100% | half |
| Reliability | LLM Latency | Line | warn=5000, fail=8000 | auto (ms) | half |
| Reliability | Guardrail Latency | Line | warn=5000, fail=8000 | auto (ms) | half |
| Reliability | Total Latency | Line | warn=5000, fail=8000 | auto (ms) | full |
| Reliability | Availability | Line | warn=99, fail=95 | 0–100% | half |

**Feature**: Each chart shows threshold reference lines as dashed horizontal lines — warn threshold in amber, fail threshold in red. When multiple metric versions exist, a version badge appears in the chart header (e.g., `v1.0 | v2.0`), and the chart can switch between versions or overlay them for comparison.

---

## 8. States & Edge Cases

| State | UI Treatment |
|-------|-------------|
| **Loading** (initial) | Grid of `Skeleton` cards — shadcn Skeleton with `animate-pulse`, matching card dimensions |
| **Loading** (refetch) | Subtle opacity reduction on existing charts + small spinner in header |
| **Empty** (no data in range) | Centered EmptyState card: `BarChart3` icon + "No evaluation data for this period" + suggestion to widen range |
| **Error** (API failure) | ErrorCard with `AlertTriangle` icon, error message, and Retry button |
| **Partial data** (some metrics missing) | Chart shows what it has; missing data points gap in the line; summary shows "N/A" |
| **Single data point** | Shows the dot, hides the line, summary shows same value for avg/min/max |
| **Very dense data** (>1000 points) | Downsample via `recharts` built-in or `lodash.sampleSize` before rendering |
| **Threshold crossing detected** | Small red/green dot on the chart line where threshold was crossed + annotation on hover |

---

## 9. File Structure

```
ai-eval-dashboard/
├── app/
│   ├── layout.tsx                    # Root layout: fonts, theme, QueryClient
│   ├── page.tsx                      # Dashboard page (server component shell)
│   ├── globals.css                   # BMO CSS variables + Tailwind directives
│   └── api/
│       └── evaluations/
│           └── history/
│               └── route.ts          # API proxy (or mock for dev)
├── components/
│   ├── ui/                           # shadcn/ui primitives (button, card, select, tabs, tooltip, dialog, skeleton, badge, scroll-area)
│   ├── dashboard/
│   │   ├── dashboard-header.tsx      # Top bar with logo, title, actions
│   │   ├── global-time-range-bar.tsx # Shared time period selector
│   │   ├── kpi-summary-row.tsx       # 4 KPI cards container
│   │   ├── kpi-card.tsx              # Single KPI stat card
│   │   ├── metrics-tabs.tsx          # Tab container (Safety / Performance / Reliability)
│   │   ├── chart-card.tsx            # Wrapper: header + chart + summary
│   │   ├── metric-line-chart.tsx     # Recharts line chart with thresholds
│   │   ├── time-period-selector.tsx  # Per-chart or global time picker
│   │   ├── detail-dialog.tsx         # Full trace inspection modal
│   │   ├── chart-summary-bar.tsx     # Avg/min/max footer
│   │   └── trend-indicator.tsx       # ↑↓ arrow + percentage change
│   └── shared/
│       ├── empty-state.tsx           # Reusable empty state
│       ├── error-card.tsx            # Reusable error with retry
│       └── metric-badge.tsx          # Pass/warn/fail color badge
├── lib/
│   ├── utils.ts                      # cn() utility
│   ├── api.ts                        # API client (fetch wrapper)
│   ├── metrics.ts                    # Metric definitions, thresholds, labels
│   ├── time-periods.ts               # Time period presets and date math
│   └── aggregation.ts                # KPI computation helpers
├── hooks/
│   ├── use-evaluations.ts            # React Query hook for evaluation data
│   ├── use-time-period.ts            # Time period state management
│   └── use-kpi-aggregation.ts        # Compute KPI summary from data
├── types/
│   └── evaluation.ts                 # TypeScript types matching API response
├── tailwind.config.ts
├── components.json                   # shadcn/ui config
├── next.config.ts
├── package.json
└── tsconfig.json
```

---

## 10. Implementation Phases

### Phase 1: Scaffold & Design Tokens (Day 1)
1. `create-next-app` with TypeScript, Tailwind, App Router
2. Install & configure `shadcn/ui` with `baseColor: "slate"`, `cssVariables: true`
3. Install dependencies: `recharts`, `@tanstack/react-query`, `date-fns`, `lucide-react`, `geist`
4. Copy BMO CSS variables into `globals.css` (colors, typography, spacing, shadows)
5. Configure `tailwind.config.ts` to match BMO (font family, extended colors, animation keyframes)
6. Build layout shell: header + content area

### Phase 2: Core Components (Day 2)
1. Build `KpiCard` and `KpiSummaryRow` with static mock data
2. Build `TimePeriodSelector` with preset dropdown
3. Build `ChartCard` wrapper with header + content + footer slots
4. Build `MetricLineChart` with Recharts — line + reference lines + tooltip
5. Build `TrendIndicator` (↑↓ arrow component)
6. Build `MetricBadge` (pass/warn/fail pill)
7. Build `EmptyState` and `ErrorCard`

### Phase 3: Data Integration (Day 3)
1. Define TypeScript types from the API schema
2. Build API client (`lib/api.ts`) with SWR/React Query
3. Build `useEvaluations` hook with loading/error/success states
4. Build KPI aggregation logic (`useKpiAggregation`)
5. Wire real data into chart cards
6. Implement per-chart time period filtering

### Phase 4: Polish & Detail Views (Day 4)
1. Build `DetailDialog` with full metric trace inspection and version metadata
2. Add chart summary bar (avg/min/max per period)
3. Add skeleton loading states for all cards
4. Add threshold crossing detection and annotation
5. Responsive testing (375px → 1440px)
6. Accessibility pass: keyboard nav, aria-labels, focus rings, reduced-motion

### Phase 5: Advanced Features (Day 5+)
1. Auto-refresh toggle with configurable interval
2. Date range picker for custom ranges
3. Export to CSV/PNG per chart
4. Alert badge when metrics drop below threshold (header notification)
5. Comparison mode (this period vs previous period)
6. **Metric version overlay**: When a policy version bump occurs, charts show both v1.0 and v2.0 lines with different stroke styles (solid vs dashed) so teams can compare scoring behavior before/after algorithm changes

---

## 11. Key Design Decisions

1. **Recharts over Chart.js**: React-native composability wins over imperative canvas API. Recharts components (Line, ReferenceLine, Tooltip) are first-class React citizens that work naturally with shadcn/ui styling and Tailwind. The BMO project has no existing chart library dependency, so there's no lock-in.

2. **Per-chart time selectors, not global-only**: Different metrics have different cadences — latency is noisy and needs shorter windows; style/groundedness trends need longer windows to be meaningful. Each chart defaults to the global selector but can be overridden independently.

3. **Dark-default with OS light mode support**: Dark mode is the default (matching monitoring dashboards and always-on screens). Light mode triggers automatically via `@media (prefers-color-scheme: light)`, exactly matching BMO's approach. No manual toggle — the OS setting controls the theme, keeping the CSS variable token system identical across both modes.

4. **Tab-based metric grouping**: Safety / Performance / Reliability mirrors the eval engine's own categorization, making the mental model consistent between the data pipeline and the dashboard.

5. **Threshold lines on every chart**: The eval engine's pass/warn/fail thresholds are the most important context for interpreting scores. Making them always visible as reference lines means no need to memorize thresholds per metric.

6. **Real backend API with proxy support**: The Next.js API route proxies requests to the actual backend, allowing the dashboard to work in development against any backend URL (configured via env var). Mock data fallback for demo/development without a running backend.

---

## 12. Backend API Requirements (for the backend team)

The dashboard expects a single endpoint:

```
GET /api/evaluations/history
  ?from=ISO_8601_datetime
  &to=ISO_8601_datetime
  &limit=number (default 2000, max 5000)

Response: { evaluations: EvaluationRecord[], total: number, from: string, to: string }
```

**Data source**: The backend reads `conversations.jsonl` from the adaptive-synth-eval output directory (or equivalent evaluation artifact), filters by timestamp range, and returns the records matching the schema in Section 6.1.

Each record in `conversations.jsonl` corresponds to one evaluation event — the backend should extract and normalize the metric fields to match the dashboard's expected schema. If certain metrics don't exist in all records (e.g., older runs before a metric was added), the backend should return `null` for those fields rather than omitting them.

**Batch AI eval integration**: The backend also exposes endpoints to trigger batch AI evaluation runs (designed in a separate backend spec). The dashboard does not directly trigger evaluations — it only reads results. The backend is responsible for:
- Running batch evaluations against `conversations.jsonl` data
- Storing evaluation results in a queryable format
- Serving results via the `/api/evaluations/history` endpoint
- Optionally providing a `/api/evaluations/status` endpoint so the dashboard can show whether a batch eval is currently running
