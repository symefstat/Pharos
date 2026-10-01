# Deployment image for the Pharos SPA (Vite + React).
#
# Multi-stage: a Node stage compiles the app, then the built assets are copied
# into a bare nginx stage. The toolchain — Node, npm, 174 MB of node_modules,
# TypeScript — exists only inside the first stage and is discarded. What ships is
# nginx plus a few hundred KB of static files, so the attack surface and the pull
# time both shrink to almost nothing.

# ── stage 1: build ───────────────────────────────────────────────────────────
FROM node:24-alpine AS build

WORKDIR /app

# Manifests first, for the same layer-caching reason as the API image: `npm ci`
# is the slow step and it only needs to re-run when the lockfile changes.
COPY package.json package-lock.json ./

# `npm ci` rather than `npm install` — it installs exactly what package-lock.json
# pins and fails if the lockfile is out of step, instead of quietly resolving new
# versions. Reproducibility is the whole point of building in a container.
RUN npm ci

COPY . .

# Runs `tsc -b && vite build` per package.json, so a type error fails the image
# build rather than shipping broken output.
RUN npm run build

# ── stage 2: serve ───────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx's own image already sets a correct CMD and runs in the foreground.
