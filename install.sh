#!/bin/bash
set -euo pipefail

# TGBiRelay（TG 双向机器人中枢）一键安装器
# 可通过设置 REPO_BASE / APP_DIR / SERVICE_NAME 自定义部署位置与镜像源

APP_DIR=${APP_DIR:-/opt/tg_birelay}
SERVICE_NAME=${SERVICE_NAME:-tgbirelay}
REPO_BASE=${REPO_BASE:-https://raw.githubusercontent.com/tohka0x01/tg_birelay/master}
PYTHON_BIN="$APP_DIR/venv/bin/python"
MODULE_ENTRY="tg_birelay.app"
FILES=(tg_birelay/__init__.py tg_birelay/app.py tg_birelay/database.py tg_birelay/captcha.py README.md install.sh)
APT_UPDATED=0

need_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "⚠️  请使用 root 或 sudo 运行该脚本。"
    exit 1
  fi
}

ensure_pkg() {
  local pkg=$1
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    if [[ $APT_UPDATED -eq 0 ]]; then
      echo "🔄 正在刷新 apt 软件源..."
      apt-get update -qq >/dev/null 2>&1 || true
      APT_UPDATED=1
    fi
    echo "📦 安装依赖：$pkg"
    apt-get install -y -qq "$pkg"
  fi
}

install_prereqs() {
  ensure_pkg curl
  ensure_pkg git
  ensure_pkg python3
  ensure_pkg python3-venv
  ensure_pkg python3-pip
}

fetch_sources() {
  mkdir -p "$APP_DIR"
  for file in "${FILES[@]}"; do
    echo "📥 获取 $file"
    target="$APP_DIR/$file"
    mkdir -p "$(dirname "$target")"
    curl -fsSL "$REPO_BASE/$file" -o "$target"
  done
}

setup_venv() {
  if [[ ! -d "$APP_DIR/venv" ]]; then
    python3 -m venv "$APP_DIR/venv"
  fi
  "$PYTHON_BIN" -m pip install --upgrade pip >/dev/null 2>&1
  "$PYTHON_BIN" -m pip install -q python-telegram-bot==20.7 python-dotenv
}

write_env_file() {
  read -rp "请输入管理 Bot 的 Token: " MANAGER_TOKEN
  while [[ -z "$MANAGER_TOKEN" ]]; do
    read -rp "Token 不能为空，请重新输入: " MANAGER_TOKEN
  done
  read -rp "请输入接收日志的频道/群 ID（可留空）: " ADMIN_CHANNEL
  DATABASE_PATH=${DATABASE_PATH:-$APP_DIR/tg_hosts.db}

  {
    echo "MANAGER_TOKEN=$MANAGER_TOKEN"
    [[ -n "${ADMIN_CHANNEL:-}" ]] && echo "ADMIN_CHANNEL=$ADMIN_CHANNEL"
    echo "DATABASE_PATH=$DATABASE_PATH"
  } >"$APP_DIR/.env"

  echo "✅ 已写入 $APP_DIR/.env"
}

install_service() {
  cat >/etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=TGBiRelay Host Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=PYTHONPATH=$APP_DIR
ExecStart=$PYTHON_BIN -m $MODULE_ENTRY
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
}

install_app() {
  need_root
  install_prereqs
  mkdir -p "$APP_DIR"
  APP_DIR=$(cd "$APP_DIR" && pwd)
  PYTHON_BIN="$APP_DIR/venv/bin/python"
  fetch_sources
  setup_venv
  write_env_file
  install_service
  echo "🎉 部署完成，可使用 journalctl -u $SERVICE_NAME -f 查看日志。"
  echo "👉 子 Bot Token、Topic 群 ID 等均可在 Telegram 管理面板交互配置。"
}

uninstall_app() {
  need_root
  systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  rm -rf "$APP_DIR"
  echo "🗑️  已卸载并清理 $APP_DIR。"
}

main_menu() {
  echo "=============================="
  echo "  TGBiRelay 安装器"
  echo "=============================="
  echo "1) 安装 / 更新"
  echo "2) 卸载"
  echo "3) 退出"
  read -rp "请选择操作 [1-3]: " choice
  case "$choice" in
    1) install_app ;;
    2) uninstall_app ;;
    *) echo "Bye." ;;
  esac
}

main_menu
