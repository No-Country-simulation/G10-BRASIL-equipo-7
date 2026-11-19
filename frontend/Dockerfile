FROM node:24-alpine AS build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
COPY config/chat.json /app/config/chat.json
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist/ /usr/share/nginx/html/

EXPOSE 8080
