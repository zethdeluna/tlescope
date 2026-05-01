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

# Replace nginx's default config with ours
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled assets from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]