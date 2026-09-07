#!/bin/sh
set -e

# 自动纠正宿主机挂载卷 (data 和 logs 目录) 的所有者与权限，防止非 root 容器由于权限问题崩溃
mkdir -p /app/data /app/logs
chown -R app:app /app/data /app/logs 2>/dev/null || chmod -R 777 /app/data /app/logs 2>/dev/null || true

# 如果是以 root 运行且安装了 gosu，则安全降权为 app 用户执行应用主进程
if [ "$(id -u)" = '0' ] && command -v gosu >/dev/null 2>&1; then
    exec gosu app "$@"
fi

exec "$@"
