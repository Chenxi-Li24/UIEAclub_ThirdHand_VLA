# Guest workspace — 2026-11-13

Login now links to /guest#control via Continue as Guest. Guests can orbit/zoom the hosted 3D robot and adjust six preview joint sliders without an account. The guest module creates no session, WebSocket or device request; controls update only the browser model. Real control, account history, saved waypoints, camera streams and AI actions require existing authenticated access and are not exposed by this guest entry.

services/cloud-api/src/guest-pages.js renders the public shell and serves a bounded /guest-assets/ allowlist for model and presentation resources. Private /control-assets/ and /api/v1/ authentication remain unchanged. The final guest import map has its own CSP hash after URL rewriting. No database or credential changes. No new dependencies. Local cloud startup uses the normal staging-main entry; Nginx adds only /guest and /guest-assets/ routes to the existing cloud upstream.

Deployed release: /opt/thirdhand-stage/releases/guest-20261113. Previous release: /opt/thirdhand-stage/releases/workspace-20261113. Nginx backup: /var/backups/thirdhand/nginx-before-guest-20261113.conf. Rollback restores that config, validates/reloads Nginx, atomically restores the previous current symlink and restarts thirdhand-stage.service.

Validation: seven guest/auth/bootstrap tests passed, including anonymous API rejection, a denied legacy control-script request and final import-map CSP hashing. Public /guest returns 200; anonymous devices returns 401; guest-assets/js/main.js returns 404. Browser loaded the model and six sliders; J1 changed from 0 to 10 degrees with no API or WebSocket requests, and real send stayed disabled. No robot action or account mutation occurred.
