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

The initial production implementation includes creation, real Project/Conversation/GitHub/File source pickers, recent visuals, search, node inspection, evidence levels, upstream/downstream reachability, authored path finding, version history, visual-to-visual comparison, SVG rendering, standalone HTML export, and an Ask Vishnu handoff.

## Trust boundary

Visualize distinguishes visual structure from evidence. A relationship in the visual IR is an authored relationship; reachability does not claim runtime impact, blast radius, breakage, or causality. Nodes carry one of these evidence levels:

- `verified`
- `strong`
- `inferred`
- `user_supplied`
- `unverified`

The UI preserves those labels instead of presenting every AI-authored claim as verified fact. Public repository tree evidence is currently `strong`; deeper source-line analyzers may promote facts only after deterministic verification.

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

Authored coordinates are preserved. The deterministic layout only fills missing coordinates, so repository-specific analyzers and later higher-quality layout agents can own composition without changing the viewer contract.

## Persistence

`visual_intelligence.store.VisualStore` owns `visual-intelligence.sqlite3` and creates:

- `visualizations`
- `visualization_revisions`

Every graph mutation creates a revision. Visual records can be scoped to `project_id` and `conversation_id` and record their source kind/reference.

## API

Owner-authenticated routes live under `/iphone/api/visualizations`:

- `GET /iphone/api/visualizations`
- `POST /iphone/api/visualizations`
- `POST /iphone/api/visualizations/from-file`
- `POST /iphone/api/visualizations/compare`
- `GET /iphone/api/visualizations/{id}`
- `PATCH /iphone/api/visualizations/{id}`
- `DELETE /iphone/api/visualizations/{id}`
- `POST /iphone/api/visualizations/{id}/refresh`
- `GET /iphone/api/visualizations/{id}/revisions`
- `POST /iphone/api/visualizations/{id}/reach`
- `POST /iphone/api/visualizations/{id}/path`
- `GET /iphone/api/visualizations/{id}/artifact`

The routes use the same durable owner-device authentication used by the rest of the Vishnu PWA.

## Native context adapters

### Projects

The UI opens the canonical project list. When `source_kind=project` and `project_id` are supplied, the API reads the canonical project store and builds a Project Map from the real goal, tasks, milestones, source files, active/blocked/review work, and task ownership. A refresh re-reads current project state.

### Conversations

The UI opens the canonical conversation list. When `source_kind=conversation` and `conversation_id` are supplied, the API reads the canonical continuity store and composes the visual source from persisted owner/Vishnu messages. A refresh re-reads the conversation.

### GitHub

The public GitHub adapter accepts only canonical HTTPS repository URLs on `github.com`, resolves the repository metadata/default branch through the fixed GitHub API host, reads the repository tree, and produces an Architecture graph whose nodes include repository-path evidence. It does not perform arbitrary URL fetching and does not label repository-tree inference as verified source-code proof.

### Files

`POST /from-file` accepts an owner-authenticated base64 file payload up to 6 MB. The extractor supports PDF, DOCX, CSV, JSON/JSONL/YAML, Markdown/text, and common source-code formats. Extracted content becomes the visual source; unsupported binaries fail closed. The current implementation keeps the extracted text owner-scoped inside Vishnu visual persistence.

### Knowledge

The graph/evidence contracts are ready for a direct Knowledge adapter, but private Knowledge is not automatically exposed or made shareable by this implementation.

## UI isolation

The main `pwa/index.html` is intentionally not expanded with another large inline feature. `server.visualize_ui.VisualizeUiMiddleware` injects four isolated assets only into the canonical `/iphone` HTML shell:

- `/iphone/visualize-workspace.css`
- `/iphone/visualize-sources.css`
- `/iphone/visualize-workspace.js`
- `/iphone/visualize-sources.js`

API, manifest, service-worker and other asset responses are untouched. If a downstream HTML response is already content-encoded, the middleware does not attempt unsafe byte rewriting.

## Security and privacy

- Visual APIs require a trusted, active Vishnu owner device.
- Visual data is owner-scoped in persistence.
- Project and conversation hydration use already-authorized server-side stores.
- Public GitHub fetching is host-bounded to GitHub's repository API and rejects arbitrary hosts/paths.
- File payloads have a size limit and an explicit supported-format allowlist.
- Standalone artifact export is authenticated at generation time.
- Private memory/knowledge sharing is not automatically enabled.
- The viewer displays work state and authored structure, not hidden chain-of-thought.

## Qualification

CI compiles the new Python package, syntax-checks both browser bundles with Node, and runs dedicated Visualize engine/source-adapter tests before the repository-wide qualification suite.

## Next depth upgrades

The typed IR is designed so source-line/code-symbol verification, direct Knowledge maps, live-project update policies, PNG/PDF/WebP exports, guided presentation views, richer repository dependency analysis, and the planned 3D Project Structure can reuse the same canonical graph rather than creating separate diagram data models.
