# Web model dependencies

- Existing Three core remains revision 163. `loaders/GLTFLoader.js` and
  `utils/BufferGeometryUtils.js` are unmodified files from npm `three@0.163.0`,
  matching the existing core; MIT license in `three-r163.LICENSE.txt`.
- `meshopt_decoder.module.js` is unmodified from npm `meshoptimizer@0.22.0`;
  MIT license in `meshoptimizer-0.22.0.LICENSE.md`. The build-time encoder version
  is pinned in package-lock.json. No CDN or external script origin is used.
- The protected workspace CSP allows `wasm-unsafe-eval` for this WebAssembly
  decoder. It does not allow JavaScript `unsafe-eval`, arbitrary inline scripts,
  external origins, or access to legacy SDK/WebSocket routes.

References: [Three GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html),
[EXT_meshopt_compression specification](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Vendor/EXT_meshopt_compression).
