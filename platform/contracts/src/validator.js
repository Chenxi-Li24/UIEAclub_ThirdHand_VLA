const fs = require('node:fs');
const path = require('node:path');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');

function createContractValidator() {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  const schemaDir = path.resolve(__dirname, '..', 'schemas');
  const schemas = new Map();

  for (const filename of fs.readdirSync(schemaDir).filter(name => name.endsWith('.json')).sort()) {
    const schema = JSON.parse(fs.readFileSync(path.join(schemaDir, filename), 'utf8'));
    ajv.addSchema(schema);
    schemas.set(schema.$id, schema);
  }

  return {
    schemas,
    validate(schemaId, value) {
      const validator = ajv.getSchema(schemaId);
      if (!validator) {
        return {
          ok: false,
          errors: [{ path: '', keyword: 'unknown_schema', message: `unknown schema: ${schemaId}` }],
        };
      }
      const ok = validator(value);
      return {
        ok: Boolean(ok),
        errors: (validator.errors || []).map(error => ({
          path: error.instancePath,
          keyword: error.keyword,
          message: error.message || 'validation failed',
        })),
      };
    },
  };
}

module.exports = { createContractValidator };
