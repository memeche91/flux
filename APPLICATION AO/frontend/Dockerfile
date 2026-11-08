# Étape 1 : compilation de l'interface React
FROM node:22-alpine AS compilation
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Étape 2 : serveur web Caddy (léger, HTTPS automatique possible)
FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=compilation /app/dist /srv
