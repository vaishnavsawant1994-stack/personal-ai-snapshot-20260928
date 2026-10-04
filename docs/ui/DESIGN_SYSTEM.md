# Vishnu product design system

Status: implemented for the responsive web experiences and introduced as shared semantic tokens for the native companions. The values below are Vishnu project tokens. They are informed by direct reference observations but are **not** represented as ChatGPT's internal design specification.

## Reference observations

On 4 October 2026, the public logged-out ChatGPT web application was viewed at 1363 × 936 CSS pixels. In that state, the sidebar measured 260 px; the welcome heading computed to 24 px with a 28 px line height and regular weight; the composer text computed to 17 px; and the top-left menu hit area measured 44 × 44 px. The main content was centered, with restrained neutral surfaces and clear separation between navigation, welcome copy, and the composer. These are observations of one public web state and viewport, not official values to copy as a fixed specification. The public interface may change.

The official help pages document interaction patterns that are useful for this product: the Android two-line menu opens recent chat history and the iOS menu exposes Recents and conversation actions. These help pages do not publish typography or spacing tokens:

- [ChatGPT Android chat history](https://help.openai.com/en/articles/8167621-how-can-i-access-my-chat-history-in-the-chatgpt-android-app)
- [ChatGPT iOS app FAQ](https://help.openai.com/en/articles/7885016-chatgpt-ios-app-faq)

## Semantic typography

Web uses rem-based values and fluid `clamp()` values. Native interfaces map roles to platform text styles and keep Dynamic Type / scaled text enabled.

| Role | Vishnu web token | Usage | Narrow layout |
|---|---|---|---|
| Display | 30–32 px / 38–40 px | Rare welcome or hero statement | Fluidly caps at 32 px; wraps naturally |
| Page title | 22–24 px / 29–31 px | Main screen title | 22 px minimum; balanced wrap |
| Section title | 18–20 px / 24–27 px | Major section | 18 px minimum; may wrap |
| Subsection | 16–18 px / 22–24 px | Card group or subsection | 16 px minimum; no forced single line |
| Body / conversation | 16 px / 24 px | Messages, primary reading text | Retains 16 px; long content wraps |
| Supporting | 14 px / 21 px | Descriptions and helper copy | Retains 14 px |
| Control | 14 px / 19 px | Buttons, filters, tabs, labels | Wraps or stacks rather than shrinking |
| Metadata | 12 px / 17 px | Dates and status details | Retains 12 px; labels can wrap |
| Micro | 11 px / 15 px | Decorative or nonessential metadata | Use sparingly; may wrap |

Markdown content uses the semantic page/section/subsection roles, 1.5 body leading, readable list spacing, a bordered quote treatment, inline code at 0.9em, and preformatted code blocks with an internal horizontal scroll region. Markdown tables scroll inside the table region and do not widen the page. Native iOS uses system `.largeTitle`, `.title3`, `.headline`, `.body`, `.subheadline`, `.callout`, and `.caption` roles; Android uses the `sp` values in `PersonalAITheme.Type`; desktop uses the corresponding `TYPE` map in `ui/design_tokens.py`.

## Spacing, content, and controls

Spacing tokens are 4, 8, 12, 16, 20, 24, 32, 40, 48, and 64 px, represented in the web files as rem units. Semantic aliases cover page gutter, section gap, control gap, card padding, and dialog padding. The long-form reading width is 48 rem; conversation content is limited to 52 rem; broad management work areas cap at 78 rem. Tables, dashboard grids, and graph work areas may use their own labelled, local scrolling region.

Standard controls use a 44 px minimum web height, and icon-only controls use a 44 × 44 px target. Fields are at least 44 px high (the desktop and iOS companions use native minimums; Android fields are 48 dp). Common web icons use 16 px inline, 20 px regular, and 24 px prominent sizes. Focus uses a visible two-pixel accent outline and offset. Hover and pressed effects do not change layout dimensions. Disabled controls lower emphasis but retain readable labels; loading states retain their control size. Reduced-motion preferences remove decorative motion.

## Surfaces and responsive rules

- Home remains the brand and surface reference: Vishnu colors, logo, icons, and animated sphere are preserved.
- Page headers keep title, description, and actions in wrapping, min-width-safe layouts.
- Cards share the Home-derived dark surface, subtle border, and rounded corners; sections retain their distinct task hierarchy.
- Buttons and filters wrap before their labels become unreadable. Search and form fields use a 16 px mobile floor where needed to avoid browser auto-zoom.
- Dialogs and drawers are capped to the dynamic viewport and safe-area insets. Long bodies scroll internally, actions stay reachable, and short-height layouts reduce excess header spacing.
- The memory graph intentionally keeps a 900 px minimum SVG inside an accessible labelled horizontal scroll region because shrinking its labels made the graph unreadable. Tree content wraps within the page.
- Chat messages and code/table regions wrap or scroll locally. The composer reserves safe-area padding and is included in narrow and keyboard-open browser tests.
- iOS retains native Forms, controls, keyboard behavior, and Dynamic Type. Android retains native scaled text and a vertical scroll container. Desktop Settings now scrolls internally and companion dialogs choose an initial size from the available screen.

Color and surface values preserve each companion's existing visual identity. This work does not alter account, API, authentication, persistence, or product workflows.

## Screen and state inventory

| Surface | Screens / states inventoried | Automated coverage in this change |
|---|---|---|
| Main PWA (`pwa/index.html`) | Home and sphere; chat, conversation list/search, Today, Timeline, Memory, Ambient Memory, Graph, Tree, Knowledge, Activities, Apps & Tools, Workflows, Trusted Devices, Dashboard, Settings, Owner, System Status; signed-in/out, empty, loading, authorization error, creation/confirmation dialog, timeline/conversation/app drawers, mobile composer | Existing Playwright PWA qualification: all 10 module routes at 13 widths; Home sweep from 320–2560 in 32 px increments; representative dialogs/drawers, long content, signed-out timeline, short landscape, keyboard, reduced motion, and 200% / 400%-equivalent CSS reflow. Screenshots exported as CI artifacts. |
| Standalone PWA snapshot (`personal-ai/pwa/index.html`) | Signed-out enrollment and owner-password screens; same legacy app entry and feature modules as the main PWA snapshot | New Playwright qualification checks its signed-out screens at the same 13 widths, short-height, keyboard focus, reduced motion, and five screenshot artifacts. Its authenticated module fixture remains shared with the current served PWA route rather than repeated for the legacy copy. |
| Web companion (`web-companion/`) | Home, Memory, Control/pairing, emergency controls, Dashboard, reply/approval, unpaired/offline states, fixed Ask composer | New Playwright qualification across exact widths plus 40 px intermediate sweep, short-height, keyboard focus, reduced motion, touch target, and screenshot artifacts. |
| iOS companion | Cloud link, computer endpoint, pairing, connection, voice, notifications, security/forget-device | Shared token map added; existing iOS project workflow is the compile/test gate. Real device, keyboard, and Dynamic Type size sweep remain manual. |
| Android companion | Cloud link, advanced pairing expand/collapse, connection service, secure fields and offline/paired states | Shared token map applied; existing Android build/instrumentation workflow is the compile/test gate. Physical-device, keyboard, and font-scale checks remain manual. |
| Desktop application | Home, conversation, memory overview/tree/graph/timeline, dashboard, apps/tools, settings, owner control tabs, diagnostics and confirmation dialogs | Shared semantic QSS and screen-aware initial dialog/window sizing added. Pytest and package checks cover behavior/build; desktop visual snapshots at high DPI/short height still require a GUI-capable runner. |

The actual mobile account sign-in flows and owner-only tools continue to use the existing integration/security checks; UI fixtures do not claim that a real owner login was exercised.

## Verification and evidence boundaries

The existing PWA Playwright suite covers 320, 360, 375, 390, 430, 600, 768, 820, 1024, 1280, 1440, 1920, and 2560 px, plus intermediate Home widths. It exercises short and tall viewports, landscape, mobile keyboard emulation, long text, dialogs and drawer states, keyboard Tab navigation, reduced motion, and 200% / 400%-equivalent CSS widths. Browser chrome zoom itself is not controllable by Playwright in this suite; text zoom and physical-browser checks remain pending. The new web companion suite repeats the fluid width and short-height checks and writes five representative screenshots as workflow artifacts.

The merged responsive baseline before this design-system change is available in the `personal-ai-mobile-preview` artifact from GitHub Actions run `37218419085` (artifact `11309445384`). The new companion workflow also captures before screenshots from the PR base and after screenshots from the branch at phone, tablet, desktop, and wide widths. PWA and companion screenshots are headless Chromium evidence, not physical phone/tablet captures. iOS/Android physical devices, microphone hardware, landscape/keyboard combinations on hardware, Qt high-DPI screens, and an authenticated owner-only session are not claimed as passed.
