# Vishnu Visualize — Authoritative UI Contract

Status: frozen for PR #116 parity work.

The owner-approved eight-screen Visualize reference is the authoritative visual contract for the first production release. Functional behavior must stay real; unsupported behavior must never be faked to satisfy the reference.

## Global rules

- Vishnu identity only. No Archify/OpenAI branding or copied assets.
- Preserve the existing Vishnu dark navy/black product language with restrained cyan/blue/violet accents.
- Primary navigation remains a distinct slide-over/minimized Vishnu navigation surface; Visualize appears between Activities and Tools.
- Mobile is a first-class target. Use safe-area-correct spacing and avoid squeezing desktop side panels into phone layouts.
- Bottom-anchored controls preserve the canonical 24 px product inset where the underlying Vishnu shell exposes it.
- Viewer state is presentation state; canonical graph/persistence data remains unchanged.
- Evidence labels remain honest: verified, strong, inferred, user supplied, unverified. Reachability is never labelled runtime impact or blast radius.
- Hidden chain-of-thought is never displayed. Live/working visuals may expose structured task/agent state only.

## Screen 1 — Navigation menu / Visualize selected

Required state:

- Standard Vishnu navigation hierarchy.
- Home, Today, Conversations, Projects, Memory, Knowledge, Activities, Visualize, Tools, Workflows.
- Visualize sits directly between Activities and Tools.
- Visualize selected row uses the owner-approved blue-to-violet active treatment.
- Settings and Owner Controls remain separated in the lower navigation area.

## Screen 2 — Visualize home / desktop

Required composition:

- Existing Vishnu navigation at left; Visualize content occupies the main area.
- Header/search row with search field, Create Visual action, notification controls/profile affordance where supplied by the host shell.
- H1: `Visualize`.
- H2/hero line: `Turn anything into a visual system`.
- Supporting copy: structure, flows, dependencies, work and evidence with Vishnu.
- Create section uses five choices in the reference hierarchy:
  1. From a Project
  2. From GitHub
  3. From Conversation
  4. From Files & Sources
  5. Describe it
- Desktop create layout is 3 cards on the first row, 2 cards on the second row.
- Recent Visuals follows with visual thumbnails, title, type/status badges and concise metrics.
- Gallery is reachable from the home surface.

## Screen 3 — Gallery / desktop

Required composition:

- Page heading `Gallery` and short explanatory copy.
- Category tabs: All, Architecture, Workflows, Sequences, Data, Lifecycles, Projects.
- Desktop grid is three columns.
- Owner-approved example set for the first release:
  - Vishnu Agent Runtime
  - Project Execution
  - AI Provider Routing
  - Memory System
  - Approval Workflow
  - GitHub Development
  - Authentication Flow
  - Tool Execution
  - Knowledge Map
- Gallery examples act as templates: selecting one must result in a real generated/stored visual when the user chooses to use it; example cards themselves are not presented as evidence-backed owner data.

## Screen 4 — Visualize home / mobile

Required composition:

- Compact top bar: hamburger, Vishnu identity, search, create.
- `Visualize` title and `Turn anything into a visual system` copy.
- Five creation sources render as a single vertical list with large tap targets.
- Recent Visuals follows in compact rows/cards.
- No desktop left/right inspector panels are squeezed into the phone.

## Screen 5 — Visual Viewer / desktop

Required composition:

- Dedicated viewer surface (main Vishnu home sidebar is not visible inside the viewer).
- Top bar includes back/Visualize breadcrumb, visual title, Live/manual state, Share, Compare, Export and overflow/menu affordance.
- Left viewer rail contains:
  - Layers: Services, Agents, Database, External, Tools, Infrastructure (only categories present may be enabled; unknown categories remain available under Other if needed).
  - Views: Overview, Agents, Memory, Security, Data, Infrastructure, API, Deployment.
- Canvas is the dominant central surface.
- Right inspector displays selected node intelligence with status, description, relationships, source evidence and evidence confidence/level.
- Bottom-left canvas controls provide zoom out, current zoom, zoom in and fit/reset.
- Layer toggles and saved view buttons must change the presentation without mutating canonical graph data.

## Screen 6 — Ask Vishnu / contextual panel

Required composition:

- Context panel has tabs Chat, Sources, Paths, Evidence.
- Chat tab clearly scopes the question to the selected visual/node.
- Sources tab lists actual evidence references available on the selected node/visual.
- Paths tab provides upstream, downstream and authored path controls/results.
- Evidence tab explains evidence level and confidence/provenance where available.
- Ask composer hands the contextual question to the canonical Vishnu chat flow. It must not fabricate a local model answer.

## Screen 7 — Node Details / mobile

Required composition:

- Dedicated full-height mobile details state, not a squeezed desktop inspector.
- Back control, selected node identity/category/evidence state.
- Tabs: Details, Sources, Relations, Actions.
- Details shows status, project/source context, description and evidence level/confidence.
- Relations exposes incoming/outgoing authored relationships.
- Actions include Ask Vishnu and upstream/downstream controls.

## Screen 8 — Visual Viewer / mobile

Required composition:

- Full-screen visual canvas with compact title/back bar.
- Canvas remains pan/zoom capable through explicit controls; page-level horizontal overflow is not required.
- Compact canvas controls: zoom out, zoom percentage, zoom in, fit/reset and export/share action where space permits.
- Selecting a node reveals a compact bottom node card with Details, Upstream and Downstream actions.
- `Ask Vishnu` is a prominent bottom action and opens the contextual mobile details/chat flow.

## Interaction requirements

- Project picker reads `/iphone/api/projects` and creates a Project Map using the selected persisted project id.
- Conversation picker reads `/iphone/api/conversations` and creates from the selected persisted conversation id.
- GitHub source accepts only the server-supported public `https://github.com/<owner>/<repo>` URL contract.
- Files use `/iphone/api/visualizations/from-file` and server format/size validation.
- Describe it creates through `/iphone/api/visualizations`.
- Search filters/highlights visual nodes or gallery/recent visual entries depending on surface.
- Share uses native Web Share when available and a safe same-origin artifact fallback otherwise.
- Compare uses `/iphone/api/visualizations/compare`.
- Export opens the authenticated standalone HTML artifact.
- Upstream/downstream use `/reach`; path uses `/path`; history uses `/revisions`.
- All actions expose visible loading/error/empty states.

## Browser qualification contract

The Playwright Visualize suite must capture these files from the real Visualize production bundle injected into the canonical `/iphone/` shell:

1. `visualize-navigation-desktop.png`
2. `visualize-home-desktop.png`
3. `visualize-gallery-desktop.png`
4. `visualize-home-mobile.png`
5. `visualize-viewer-desktop.png`
6. `visualize-contextual-ask-desktop.png`
7. `visualize-node-details-mobile.png`
8. `visualize-viewer-mobile.png`

The suite must also assert no page errors, no horizontal page overflow at the mobile viewport, accessible interactive controls, working gallery filters, viewer node selection, layer toggles, contextual tabs, reach/path calls and back navigation.

Passing browser automation proves the implementation is functional and visually capturable; final pixel-level acceptance still requires comparing the generated screenshots with the owner-approved reference and completing the physical-iPhone acceptance checks before merge/deploy.