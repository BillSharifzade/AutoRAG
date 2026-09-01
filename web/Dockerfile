# syntax=docker/dockerfile:1
# The Next.js console. Serves the UI on :3000 and proxies /v1/* and /health to
# the API container.

# --- dependencies ------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- build -------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# next.config.ts bakes this into the rewrite rules during `next build`, so the
# API address must be known here. Compose passes the service name.
ARG KARAG_API_URL=http://api:8000
ENV KARAG_API_URL=$KARAG_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runtime -----------------------------------------------------------------
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs

# server.js does not bundle public/ or .next/static — both are copied in beside
# it, which is where the standalone server expects to find them.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
