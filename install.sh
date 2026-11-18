#!/bin/sh
# 童阅写稿器 一键安装 / 升级（飞牛 NAS 或任何装好 docker 的 Linux）
#
# 用法：
#   sh install.sh                    # 交互执行，会提示输入 sudo 密码
#   SUDO_PASS='你的密码' sh install.sh # 非交互执行
#   PORT=8123 sh install.sh          # 换端口
#   IMAGE=ghcr.io/jankxia/kidswriter:latest sh install.sh
set -e

DIR=${DIR:-/vol1/1000/kidswriter}
IMAGE=${IMAGE:-ghcr.io/jankxia/kidswriter:v1.1}
PORT=${PORT:-8122}

echo "安装目录 $DIR，镜像 $IMAGE，端口 $PORT"

# 预授权 sudo，避免后面每条命令都问密码
if [ -n "$SUDO_PASS" ]; then
  echo "$SUDO_PASS" | sudo -S -p '' -v
  SUDO="sudo -S -p ''"
else
  sudo -v
  SUDO="sudo"
fi

mkdir -p "$DIR/data"

cat > "$DIR/compose.yaml" <<EOF
services:
  kidswriter:
    image: $IMAGE
    container_name: kidswriter
    restart: unless-stopped
    # 这台机器 docker 默认网段常被其他容器占满，用 host 模式最省事
    network_mode: host
    volumes:
      - $DIR/data:/app/data
    environment:
      TZ: Asia/Shanghai
      KIDSWRITER_PORT: "$PORT"
EOF

cd "$DIR"
echo '--- 拉镜像 ---'
if [ -n "$SUDO_PASS" ]; then
  echo "$SUDO_PASS" | $SUDO docker compose pull
  echo '--- 启动 ---'
  echo "$SUDO_PASS" | $SUDO docker compose up -d
else
  sudo docker compose pull
  sudo docker compose up -d
fi
sleep 8

echo '--- 容器 ---'
if [ -n "$SUDO_PASS" ]; then
  echo "$SUDO_PASS" | $SUDO docker ps --filter name=kidswriter --format '{{.Names}} | {{.Status}} | {{.Image}}'
else
  sudo docker ps --filter name=kidswriter --format '{{.Names}} | {{.Status}} | {{.Image}}'
fi

echo '--- 服务 ---'
curl -s -m 8 "http://127.0.0.1:$PORT/api/config"
echo
echo "装好了：浏览器打开 http://<NAS的地址>:$PORT"
echo "数据在 $DIR/data（config.json 和 输出/）"
