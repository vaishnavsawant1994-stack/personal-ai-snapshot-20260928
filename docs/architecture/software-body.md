# Software Body and Private Self

Status: E1 foundation

## Software Body

`config/vishnu-body.yaml` is the declaration of Vishnu's governed software-body contract. The actual body is larger than the manifest and includes source code, tests, schemas, migrations, security/permission policy, skills, tools, provider contracts and workflow contracts at a specific Git revision.

The manifest is intentionally JSON-compatible YAML so core Vishnu can validate it with the Python standard library without introducing a YAML parser as a foundational dependency.

A durable body revision records:

- manifest hash and body version;
- Git revision;
- contract versions;
- lifecycle state (candidate, active, superseded or rejected); and
- activation/supersession timestamps.

Activation is an explicit state transition. Recording a candidate revision does not activate it.

## Private Self

The private Self is portable, versioned relationship and behavioral continuity. It may contain owner relationship context, communication style, personality configuration, preferences and private personal context.

It must not contain executable authority. Fields representing permissions, authorization, approval bypasses, security policy, continuation authority, auto-merge/auto-deploy or capability grants are rejected by the model boundary. Those decisions belong to the canonical permission and approval systems.

Self versions are append-only. A new version does not rewrite an earlier version.

## Runtime composition

Later runtime integration will compose identity with relevant memory, project context, current Work, evidence, permissions and provider capabilities. The selected LLM receives that context but does not own it.

This E1 slice deliberately does not change normal request execution, P10 behavior, approvals, memory, automation or provider routing.
