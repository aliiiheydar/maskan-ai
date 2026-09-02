# syntax=docker/dockerfile:1
#
# The Next.js frontend, built to a standalone server (next.config.mjs sets
# `output: "standalone"`), which is why the runtime stage carries a traced
# node_modules of a few megabytes instead of the ~500 MB install.
#
# One thing about this image is not like the backend's: NEXT_PUBLIC_* values
# are inlined into the JavaScript at *build* time, because the browser is what
# reads them and the browser never sees the container's environment. So the API
# URL is a build argument here, and changing it means rebuilding the image --
# there is no runtime knob for it, and pretending otherwise would produce a
# frontend that quietly calls localhost from someone else's machine.

FROM node:20-alpine AS deps
WORKDIR /app
# npm ci, not npm install: the lockfile is the dependency list, and a container
# build is exactly where a silently-resolved different version does damage.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
# Defaults to the API on the same host, which is what the compose files serve.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# `prebuild` vendors the MapLibre worker and the Vazirmatn faces out of
# node_modules into public/ and src/app/fonts (scripts/copy-map-assets.mjs), so
# the map and the Persian type are served from this origin rather than a CDN.
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S nodejs && adduser -S -u 10001 -G nodejs nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
