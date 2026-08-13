# 前端生产镜像（V2-5）：Vite 构建产物由 nginx 托管，/api 反代到 backend
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./

# sharp（@capacitor/assets 传递依赖）需从 GitHub 下载 libvips 预编译二进制，
# 国内服务器直连超时；npm_config_* 环境变量将其重定向到 npmmirror 镜像。
ENV npm_config_sharp_binary_host=https://registry.npmmirror.com/-/binary/sharp \
    npm_config_sharp_libvips_binary_host=https://registry.npmmirror.com/-/binary/sharp-libvips

RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
