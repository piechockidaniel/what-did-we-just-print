# What Did We Just Print, Man?

Visual identity for offset-printing orders after sheet cutting. The interface follows the supplied dark print-floor design: orange controls, a job ticket, registration marks and a reference-sheet grid. The 24 empty slots are decorative placeholders, not production imposition or a limit on saved references. Production lifecycle stages are documented but not implemented.

See [the concept document](docs/CONCEPT.md) for sheet composition, active production boundaries, cached matching, ranked evidence, limitations and the next implementation slice.

## Development (Vite + JavaScript)

Run these commands from `H:\Active Solutions\what did we just print`:

```powershell
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Use the same address every time: browser data belongs to an origin (scheme, host and port). Existing hosted catalog records do not automatically appear on localhost. The IndexedDB database name and schema remain unchanged.

```powershell
npm run check
npm run build
npm run preview
```

Production output is generated in `dist/`; preview runs at http://127.0.0.1:4173. Edit `index.html`, `src/main.js` and `src/style.css`, rather than generated files. Vite settings are in `vite.config.js` and dependency versions are locked in `package-lock.json`. The original static prototype is preserved in `archives/prototype-before-vite/`.

## Repository handoff

Include `index.html`, `src/`, `package.json`, `package-lock.json`, `vite.config.js`, `.gitignore`, `README.md` and `docs/` in the source repository. Build with `npm ci` and `npm run build`; publish the generated `dist/` folder. Keep `.openai/hosting.json` if continuing the existing private Sites deployment. Do not copy `.git/`, credentials, packaging archives or customer data. No external repository has been created for this handoff.

## Implemented prototype

Simplified business-card order intake and scanning reference catalog. Open the hosted interface or serve `dist` using `python -m http.server 8080 --directory dist` and visit http://localhost:8080.

Create an order, upload one final-trim front image per variant, and enter its name, quantity and destination. PNG/JPEG/WebP uploads are decoded before acceptance. Each order and variant gets a UUID. The catalog supports search and exports JSON containing original image data URLs, pixel dimensions, physical dimensions, destination and quantity.

Records persist in IndexedDB in the current browser and origin. This is a single-browser prototype, without shared storage, authentication for customer intake, payment, camera capture, OCR or recognition. Export backups before clearing browser data. Private hosting controls access to the interface; it does not synchronize records between devices.

For scanner integration, read `orders[].variants[]` from the exported catalog. Use the variant UUID as the identity key. Images are reference artwork rather than camera captures; visually identical references must be treated as ambiguous. Dimensions are user-entered and have not been independently verified. Use synthetic or authorized artwork for testing.


