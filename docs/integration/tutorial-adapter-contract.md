# Tutorial integration boundary

Status: proposed adapter contract; the teammate's implementation and authoritative progress storage will be connected at merge. This module does not create a second tutorial or progress table.

The backend passes the authenticated user UUID from its session, never a browser-supplied user ID. A production adapter implements:

```js
getState({ userId }) // Promise<{ status, version? }>
getEntry({ locale, theme, returnTo }) // { path } | null
verifyCompletion({ userId, version }) // Promise<{ trusted, completed, version }>
```

`status` is one of `unavailable`, `not_started`, `in_progress`, `deferred`, `completed`. Until connected, return `unavailable`, `null`, and `{trusted:false,completed:false,version:null}`. Never infer completion from a URL parameter, localStorage, or a frontend callback alone.

New users with a connected `not_started`/`in_progress` state enter the tutorial first. `deferred` users can continue into their workspace without a redirect loop. An unavailable adapter produces an explicit integration-pending state with a workspace continuation, and does not falsely claim that the tutorial was completed.

`getEntry` must return an allowlisted same-origin path. Reject protocol-relative paths, schemes, backslashes, control characters and unapproved prefixes; do not echo arbitrary `returnTo`. Return targets are workspace routes. `locale` is `en` or `zh-CN`; `theme` is validated theme configuration, with first-visit light. Tutorial entry does not connect SDK or obtain a control lease.

Merge checklist: agree adapter transport/module location, identity mapping, version semantics, trusted completion verification, permitted tutorial paths, deferred behavior, language/theme handoff, error behavior, and integration tests with the teammate. Website mode/roles remain owned by identity policy; tutorial completion never grants administrator privileges.
