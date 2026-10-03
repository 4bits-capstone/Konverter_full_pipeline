# frontend.Dockerfile — build the React app, serve it with nginx
#
# Vite inlines these env vars at BUILD time (passed as build args):
#   VITE_API_BASE_URL      — where the browser calls the backend
#   VITE_SUPABASE_URL      — Supabase project URL (for login)
#   VITE_SUPABASE_ANON_KEY — Supabase anon key (public, safe in frontend)
#
# Built automatically by docker-compose (see build.args there).

# ---- stage 1: build ----
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000/api
ARG VITE_SUPABASE_URL=https://placeholder.supabase.co
ARG VITE_SUPABASE_ANON_KEY=placeholder_key
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
RUN echo ">> Building frontend with VITE_API_BASE_URL=$VITE_API_BASE_URL"
RUN npm run build

# ---- stage 2: serve ----
FROM nginx:1.27-alpine
# SPA routing: serve index.html for client-side routes
RUN printf 'server {\n\
  listen 80;\n\
  location / {\n\
    root /usr/share/nginx/html;\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
