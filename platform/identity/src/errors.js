'use strict';
function identityError(code, message = code) { return Object.assign(new Error(message), { code }); }
module.exports = { identityError };
