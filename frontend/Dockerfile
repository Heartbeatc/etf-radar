FROM docker.1ms.run/node:22-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY . .
RUN npm run build

FROM docker.1ms.run/nginx:1.27-alpine

RUN rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
