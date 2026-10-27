# Mini-Rayyan frontend

Vite + React + strict TypeScript + Tailwind + TanStack Query. Requires Node.js
22.18+ (native config loading avoids bundler path restrictions on Windows).
Run from `frontend/`:

```powershell
npm install
npm run dev
```

Open the Vite URL (normally `http://127.0.0.1:5173`). Default mode uses a copied
snapshot of `../Docs/api-examples.json` in `src/mocks/api-examples.json`; no backend
or external request is needed. Demo changes persist in sessionStorage within the
current browser tab. Missing metadata for IDs referenced by duplicate examples
is labeled explicitly. Mock hit counts are examples, not real search results.
Mock pipeline runs demonstrate job state; they do not implement NLP algorithms.

For backend mode, create `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Restart Vite after changing it. The URL is the backend origin, **without `/api`**.
There is no fallback to mock data on a backend error. Configure backend
`CORS_ORIGINS` to include the exact frontend origin (`http://127.0.0.1:5173` or
`http://localhost:5173`). No backend configuration is changed by this frontend.

All requests go through `src/api.ts`. Pages use hash routes, so refresh works
without server rewrite rules. Mutations refresh the query cache. Fetch and
pipeline jobs show indeterminate progress and poll actual run states/counts;
the API does not provide a percentage.

Record labels, notes, undo, duplicate decisions, criteria toggles and PICO edits
use the existing decision API. PICO uses Unicode code point offsets, matching
Python. The highlighter uses React text nodes (automatic HTML escaping), validates
offsets/text and handles overlaps; it never inserts abstract text as HTML.

```powershell
npm test
npm run build
npm run preview
```

To refresh mock fixtures after an API example update (PowerShell):

```powershell
Copy-Item ../Docs/api-examples.json src/mocks/api-examples.json
```

Only frontend files are part of this implementation.
