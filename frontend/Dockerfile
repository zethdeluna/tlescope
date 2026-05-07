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

# Copy compiled assets from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Read the actual DNS resolver from /etc/resolv.conf at container start so nginx
# can re-resolve .railway.internal hostnames after a redeployment. 127.0.0.11 is
# the Docker-compose fallback; Railway's resolver will be whatever is in resolv.conf.
CMD ["/bin/sh", "-c", "RESOLVER=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf); NGINX_LOCAL_RESOLVERS=${RESOLVER:-127.0.0.11} envsubst '${BACKEND_URL} ${NGINX_LOCAL_RESOLVERS}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf; exec nginx -g 'daemon off;'"]