'use strict';
// Compatibility entry: initial administrator privileges now require a private email list.
const {main}=require('./initial-admins');
if (require.main === module) main().catch(() => { process.stderr.write('Administrator bootstrap failed; inspect account verification and existing administrator state.\n'); process.exitCode = 1; });
module.exports = { main };
