FROM node:20-alpine AS builder

WORKDIR /app

ARG VITE_SKIP_EMAIL_VERIFICATION=true
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY . .
ENV VITE_SKIP_EMAIL_VERIFICATION=$VITE_SKIP_EMAIL_VERIFICATION
RUN npm run build

FROM nginx:alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
