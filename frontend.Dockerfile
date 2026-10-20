# check=skip=SecretsUsedInArgOrEnv
# frontend.Dockerfile — build the React app, serve it with nginx
#
# The anon key is public by design (it ships in the browser bundle), so the
# SecretsUsedInArgOrEnv lint rule is skipped via the directive on line 1.
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
# nginx config with security headers; the CSP names the API and Supabase
# origins, taken from the same build args the app was built with.
ARG VITE_API_BASE_URL=http://localhost:8000/api
ARG VITE_SUPABASE_URL=https://placeholder.supabase.co
COPY deploy/frontend/nginx.conf.template /tmp/nginx.conf.template
RUN api_origin="$(echo "$VITE_API_BASE_URL" | sed -E 's#^(https?://[^/]+).*#\1#')" \
 && supabase_origin="$(echo "$VITE_SUPABASE_URL" | sed -E 's#^(https?://[^/]+).*#\1#')" \
 && supabase_ws_origin="$(echo "$supabase_origin" | sed -E 's#^http#ws#')" \
 && sed -e "s#__API_ORIGIN__#$api_origin#g" \
        -e "s#__SUPABASE_ORIGIN__#$supabase_origin#g" \
        -e "s#__SUPABASE_WS_ORIGIN__#$supabase_ws_origin#g" \
        /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf \
 && rm /tmp/nginx.conf.template \
 && nginx -t
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
