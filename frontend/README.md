# flinq (frontend)

React 19 + TypeScript + Vite + Tailwind CSS v4 + TanStack Router + TanStack Query.

See [ADR-0006](../docs/adr/ADR-0006-tech-stack.md) for the full tech stack rationale.

## Layout

```
frontend/
├── package.json
├── pnpm-lock.yaml          # generated
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── eslint.config.js
├── .prettierrc.json
├── index.html
├── src/
│   ├── main.tsx            # entry point — creates router, mounts React tree
│   ├── routeTree.ts        # TanStack Router tree (code-based)
│   ├── routes/
│   │   ├── __root.tsx      # root layout
│   │   └── index.tsx       # home page
│   ├── api/
│   │   └── client.ts       # fetch wrappers, typed API client
│   ├── stores/             # Zustand stores (placeholder)
│   ├── components/         # shared UI components (placeholder)
│   ├── styles/
│   │   └── globals.css     # Tailwind v4 import + theme tokens
│   └── vite-env.d.ts
└── tests/
    ├── setup.ts
    └── App.test.tsx
```

## Local development

```bash
corepack enable                   # one-time
pnpm install
pnpm dev                          # Vite on :5173, proxies /api and /health to :8000
pnpm test                         # Vitest
pnpm lint                         # ESLint
pnpm format                       # Prettier
pnpm build                        # Production build → dist/
```

## Production build

The production frontend is built as part of the `backend/Dockerfile` multi-stage pipeline
(the `frontend-build` stage) and served by FastAPI as static assets from
`/app/frontend/dist`. There is no separate frontend container in production —
see [architecture §5.3](../docs/architecture/2026-04-11-mvp-architecture-overview.md).