'use strict';
const { randomBytes } = require('node:crypto');
const { isolatedDatabase } = require('./database-fixture');
const { migrate } = require('../../../platform/storage/src/migrate');

async function identityFixture(t) {
  const pool = await isolatedDatabase(t); await migrate(pool);
  const mailbox = [], clock = { value: Date.parse('2026-10-30T09:00:00Z'), now() { return new Date(this.value); } };
  const { createMfa } = require('../../../platform/identity/src/mfa');
  const { createAccounts } = require('../../../platform/identity/src/accounts');
  const mfa = createMfa({ pool, keyId: 'test-key', keys: new Map([['test-key', randomBytes(32)]]), clock });
  const accounts = createAccounts({ pool, mfa, clock, publicOrigin: 'https://thirdhand.example.invalid', mail: {
    async send(message) { mailbox.push(message); }
  } });
  const token = message => new URLSearchParams(new URL(message.url).hash.slice(1)).get('token');
  async function verified(suffix) {
    const user = await accounts.register({ username: `user_${suffix}`, email: `${suffix}@example.invalid`, displayName: suffix, password: 'Test only strong passphrase 473!' });
    await accounts.verifyEmail({ token: token(mailbox.at(-1)) });
    return user;
  }
  return { pool, accounts, mfa, mailbox, clock, token, verified, password: 'Test only strong passphrase 473!' };
}
module.exports = { identityFixture };
