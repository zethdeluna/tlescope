# Frontend Dockerfile

# ----------------------------------------------------------------------------
# Stage 1: Build
# ----------------------------------------------------------------------------

FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (cached layer unless package.json changes)
COPY package*.json ./
RUN npm ci

# Inject the Cesium Ion token as a build-time ARG so it is baked into the 
# compiled JS bundle. Never hardcode it in source - pass it via --build-arg 
# in docker-compose or as a Render/Fly environment variable.
ARG VITE_CESIUM_TOKEN
ENV VITE_CESIUM_TOKEN=$VITE_CESIUM_TOKEN

COPY . .
RUN npm run build


# ----------------------------------------------------------------------------
# Stage 2: Serve
# ----------------------------------------------------------------------------

FROM  nginx:alpine

# Place the config as a template; nginx:alpine's entrypoint runs envsubst on
# /etc/nginx/templates/*.template before starting nginx, substituting any
# env vars that are currently defined (e.g. BACKEND_URL).
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Default backend URL for docker-compose; override for Railway:
#   BACKEND_URL=http://<service-name>.railway.internal:8000
ENV BACKEND_URL=http://backend:8000

# Fallback resolver (Docker's embedded DNS). nginx's 15-local-resolvers.envsh
# will override this with the actual resolver from /etc/resolv.conf if available.
ENV NGINX_LOCAL_RESOLVERS=127.0.0.11

# Copy compiled assets from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]