# Vendored three.js

Bundled so the browser view works without internet (school networks).

- Version: three.js 0.186.1 (MIT license, see `LICENSE`)
- `three.module.js`, `three.core.js`: `build/three.module.js` and
  `build/three.core.js`, minified by jsDelivr:
  `https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.min.js`
  (and `three.core.min.js`). Saved under the original names because
  `three.module.js` imports `./three.core.js`.
- `OrbitControls.js`: `examples/jsm/controls/OrbitControls.js`, unchanged.
  It imports `three`, which the pages map to `three.module.js` with an
  import map.

To update: download the same files for the new version and test the browser
view (`python -m cfsim --viewer browser examples/01_hello_fly.py`).
