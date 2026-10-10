# Vishnu Visualize

Visualize is Vishnu's native visual-intelligence workspace. It turns owner-provided descriptions and Vishnu-owned context into typed, validated, explorable visual artifacts without exposing private model chain-of-thought.

## Product surface

The PWA receives a first-class **Visualize** menu item between Activities and Tools. The workspace supports six visual models:

- Architecture
- Workflow
- Sequence
- Data Flow
- Lifecycle
- Project Map

The first production slice includes creation, recent visuals, search, node inspection, evidence levels, upstream/downstream reachability, authored path finding, version history, visual-to-visual comparison, SVG rendering, standalone HTML export, and an Ask Vishnu handoff.

## Trust boundary

Visualize distinguishes visual structure from evidence. A relationship in the visual IR is an authored relationship; reachability does not claim runtime impact, blast radius, breakage, or causality. Nodes carry one of these evidence levels:

- `verified`
- `strong`
- `inferred`
- `user_supplied`
- `unverified`

The UI must preserve those labels instead of presenting every AI-authored claim as verified fact.

## Pipeline

```text
Input / Vishnu context
        ↓
Analysis adapter
        ↓
Typed VisualGraph IR
        ↓
Semantic validation
        ↓
Deterministic layered layout
        ↓
SVG renderer
        ↓
Interactive Vishnu viewer
        ↓
Versioned persistence + export
```

Authored coordinates are preserved. The deterministic layout only fills missing coordinates, so future repository-specific analyzers and higher-quality layout agents can own composition without changing the viewer contract.

## Persistence

`visual_intelligence.store.VisualStore` owns `visual-intelligence.sqlite3` and creates:

- `visualizations`
- `visualization_revisions`

Every graph mutation creates a revision. Visual records can be scoped to `project_id` and `conversation_id` and record their source kind/reference.

## API

Owner-authenticated routes live under `/iphone/api/visualizations`:

- `GET /iphone/api/visualizations`
- `POST /iphone/api/visualizations`
- `GET /iphone/api/visualizations/{id}`
- `PATCH /iphone/api/visualizations/{id}`
- `DELETE /iphone/api/visualizations/{id}`
- `POST /iphone/api/visualizations/{id}/refresh`
- `GET /iphone/api/visualizations/{id}/revisions`
- `POST /iphone/api/visualizations/{id}/reach`
- `POST /iphone/api/visualizations/{id}/path`
- `POST /iphone/api/visualizations/compare`
- `GET /iphone/api/visualizations/{id}/artifact`

The routes use the same durable owner-device authentication used by the rest of the Vishnu PWA.

## Native context adapters

### Projects

When `source_kind=project` and `project_id` are supplied, the API reads the canonical project store and builds a Project Map from the real goal, tasks, milestones, source files, active/blocked/review work, and task ownership. A refresh re-reads current project state.

### Conversations

When `source_kind=conversation` and `conversation_id` are supplied, the API reads the canonical continuity store and composes the visual source from persisted owner/Vishnu messages. A refresh re-reads the conversation.

### Repository, files and knowledge

The public IR and evidence model intentionally leave room for repository, connector, file-index and knowledge adapters. Those adapters must attach verifiable source references and must never upgrade evidence to `verified` merely because a model inferred a component.

## UI isolation

The main `pwa/index.html` is intentionally not expanded with another large inline feature. `server.visualize_ui.VisualizeUiMiddleware` injects:

- `/iphone/visualize-workspace.css`
- `/iphone/visualize-workspace.js`

only into the canonical `/iphone` HTML shell. API, manifest, service-worker and other asset responses are untouched.

This keeps Visualize independently testable and reduces regression risk in the existing PWA.

## Security and privacy

- Visual APIs require a trusted, active Vishnu owner device.
- Visual data is owner-scoped in persistence.
- Project and conversation hydration use already-authorized server-side stores.
- Standalone artifact export is authenticated at generation time.
- Private memory/knowledge sharing is not automatically enabled by this slice.
- The viewer displays work state and authored structure, not hidden chain-of-thought.

## Next adapters

The typed IR is designed so repository intelligence, source-line evidence, file/knowledge maps, live-project update policies, PNG/PDF/WebP exports, guided presentation views, and the planned 3D Project Structure can reuse the same canonical graph rather than creating separate diagram data models.
