# Vishnu Visualize

Visualize is Vishnu's native visual-intelligence workspace. It turns owner-provided descriptions and authorized Vishnu context into typed, validated, explorable visual artifacts without exposing private model chain-of-thought.

## Product surface

The PWA exposes **Visualize** between Activities and Tools and supports six canonical models:

- Architecture
- Workflow
- Sequence
- Data Flow
- Lifecycle
- Project Map

The production surface supports creation from descriptions, Vishnu Projects, Conversations, public GitHub repositories and supported files; native Knowledge Maps, privacy-scoped Memory Maps and Live Work maps; recent visuals and Gallery; node intelligence; evidence; reachability and path finding; revisions and comparison; natural-language visual editing; presentation mode; a shared 2D/3D projection; and HTML/SVG/PNG/WebP/PDF/JSON export.

## Trust boundary

Visual structure and evidence are separate. A relationship in the visual IR is an authored relationship; graph reachability does **not** claim runtime impact, blast radius, breakage or causality. Nodes use these evidence levels:

- `verified`
- `strong`
- `inferred`
- `user_supplied`
- `unverified`

`verified` source-code evidence is reserved for exact fetched source lines pinned to an immutable GitHub commit SHA. Repository-level or heuristic interpretation is not promoted to verified merely because it came from a repository.

## Compiler-style pipeline

```text
Input / Vishnu context
        ↓
Analysis adapter
        ↓
Typed VisualGraph IR
        ↓
Deterministic layout
        ↓
Validation
        ↓
Deterministic structural repair when safe
        ↓
Re-validation
        ↓
Renderer / viewer / projections
        ↓
Versioned persistence + exports
```

A candidate graph is validated before persistence. Structurally repairable defects receive a machine-readable repair receipt; an unrecoverable candidate does not replace the last persisted good revision.

Authored coordinates are preserved. Layout only fills missing coordinates. Presentation and 3D are projections of the same canonical IDs rather than independent data models.

## Persistence

`visual_intelligence.store.VisualStore` owns `visual-intelligence.sqlite3` and persists:

- `visualizations`
- `visualization_revisions`

Every canonical graph mutation creates a revision. Visual records may be scoped to project/conversation IDs and retain source kind/reference.

## API

Owner-authenticated routes live under `/iphone/api/visualizations`:

- `GET /iphone/api/visualizations`
- `POST /iphone/api/visualizations`
- `POST /iphone/api/visualizations/from-file`
- `POST /iphone/api/visualizations/knowledge-map`
- `POST /iphone/api/visualizations/memory-map`
- `POST /iphone/api/visualizations/live-work-map`
- `POST /iphone/api/visualizations/compare`
- `GET /iphone/api/visualizations/{id}`
- `PATCH /iphone/api/visualizations/{id}`
- `DELETE /iphone/api/visualizations/{id}`
- `POST /iphone/api/visualizations/{id}/edit`
- `POST /iphone/api/visualizations/{id}/repair`
- `POST /iphone/api/visualizations/{id}/refresh`
- `GET /iphone/api/visualizations/{id}/revisions`
- `POST /iphone/api/visualizations/{id}/reach`
- `POST /iphone/api/visualizations/{id}/path`
- `GET /iphone/api/visualizations/{id}/presentation`
- `GET /iphone/api/visualizations/{id}/scene?dimension=2d|3d`
- `GET /iphone/api/visualizations/{id}/export?format=html|svg|json|png|webp|pdf`
- `GET /iphone/api/visualizations/{id}/artifact`

## Native context adapters

### Projects and Live Work

Project Map reads the canonical ProjectStore. Live Work projects goal/milestones/tasks, dependencies, assigned agents, execution-run IDs and project files from current project state. A live-work refresh re-reads the canonical project.

### Conversations

Conversation visuals read persisted canonical continuity events and refresh from that same source.

### GitHub deep source analysis

The GitHub adapter is bounded to canonical HTTPS `github.com/<owner>/<repo>` repositories and the fixed GitHub API host. Deep analysis resolves the default branch to an immutable commit SHA, reads the commit-pinned source tree, fetches a bounded set of source files and extracts supported source facts including:

- files/modules
- Python imports
- JavaScript/TypeScript relative imports
- classes/functions
- supported route declarations
- exact source-line ranges

Verified nodes/relationships retain repository, branch, commit SHA, path, exact line range and blob SHA. The earlier tree-level analyzer remains an explicit lower-depth mode and keeps `strong` evidence semantics.

### Files

Owner-authenticated file ingestion supports PDF, DOCX, CSV, JSON/JSONL/YAML, Markdown/text and common source-code formats with explicit size/type limits.

### Knowledge Maps

Knowledge Map reads the existing governed KnowledgeStore. It respects the trusted-device knowledge scope and includes private documents only when `knowledge:private` is authorized. It projects collections, current documents and canonical knowledge-memory links without changing the underlying knowledge store.

### Memory Maps

Memory Map reads the existing Second Brain Life Graph. Normal-sensitivity memories are the default. Sensitive/secret memory requires both an explicit `include_sensitive` request and the device's `memory:sensitive` authorization. Maps are snapshot visuals and remain owner-scoped.

## Natural-language visual editing

The governed edit endpoint supports explicit presentation edits such as:

- `Move Memory Engine right 180`
- `Move API to 500,300`
- `Rename API to Request Gateway`
- `Highlight Authentication Service`
- `Show only Agents and Tools`
- `Group Database and File Storage as Persistence`
- `Simplify`
- `Reset layout`

These edits are deliberately conservative: they may change presentation/grouping/labels but do not invent architectural facts. Every persisted edit creates a revision and returns an operation receipt.

## Presentation and shared 2D/3D model

Presentation mode creates guided semantic views such as Overview, Agents, Memory & Data, Security, Interfaces & APIs, Tools & Integrations and Infrastructure. Authored views may also become slides.

`scene?dimension=2d|3d` projects the same canonical nodes/edges into scene coordinates. The 3D view is therefore a projection of the VisualGraph, not a separate architecture model that can drift.

## Exports

Authenticated export supports:

- interactive HTML
- SVG
- PNG
- WebP
- PDF
- canonical JSON

Raster/PDF outputs are rendered from canonical graph coordinates. JSON exports the typed canonical graph.

## UI isolation

The existing `pwa/index.html` remains authoritative. `VisualizeUiMiddleware` injects isolated same-origin bundles only into `/iphone`:

- `/iphone/visualize-workspace.css`
- `/iphone/visualize-sources.css`
- `/iphone/visualize-advanced.css`
- `/iphone/visualize-workspace.js`
- `/iphone/visualize-sources.js`
- `/iphone/visualize-advanced.js`

Manifest, service-worker, API and unrelated asset responses are untouched.

## Security and privacy

- Visual APIs require a trusted active owner device.
- Visual persistence is owner-scoped.
- Project/conversation/knowledge/memory hydration uses existing server-side authorization boundaries.
- Public GitHub fetching is host-bounded and commit-pinned for verified source evidence.
- File payloads use size limits and allowlisted formats.
- Sensitive memory is opt-in and permission-gated.
- Private Knowledge obeys `knowledge:private` authorization.
- The UI visualizes structured work state, not hidden chain-of-thought.
- Reachability is never presented as runtime-impact proof.

## Qualification

CI compiles the complete Python package, syntax-checks all three browser JS bundles and the browser harness, runs dedicated Visual Intelligence tests, and then executes the repository-wide Vishnu qualification suite. The Playwright Visualize suite uses the production Visualize bundles inside the canonical `/iphone` shell and exercises the authoritative eight-screen UI plus advanced Edit, Presentation, 3D, exports and native-map entry points.

Physical-iPhone acceptance remains a release gate where required by the product release contract.