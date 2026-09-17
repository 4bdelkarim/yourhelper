# apps/web/Dockerfile — frontend Next.js (mode standalone)
# ============================================================
# Multi-stage : deps -> build -> runner. `output: "standalone"` (next.config.ts)
# produit .next/standalone avec un serveur Node minimal : l'image finale ne
# contient ni node_modules complet ni sources, uniquement la sortie compilée.
# NEXT_PUBLIC_API_URL est inliné au BUILD (variables NEXT_PUBLIC_* de Next) :
# c'est l'URL vue par le NAVIGATEUR, donc http://localhost:8000 depuis la
# machine hôte (cf. build arg dans docker-compose.yml).

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
