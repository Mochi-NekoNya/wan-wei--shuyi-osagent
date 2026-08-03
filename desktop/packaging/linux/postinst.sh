#!/bin/sh
# postinst — 枢忆·花朝 deb/rpm 安装后脚本
# 遵循麒麟桌面软件规范：刷新 desktop 数据库与图标缓存
set -e

if [ -x /usr/bin/update-desktop-database ]; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# Electron 沙箱所需的 chrome-sandbox 权限。这里必须失败闭合；若权限设置失败却
# 继续完成安装，应用只能以 --no-sandbox 启动，会把打包故障伪装成可用安装。
SANDBOX="/opt/wanwei-shuyi-desktop/chrome-sandbox"
if [ ! -f "$SANDBOX" ]; then
  echo "wanwei-shuyi-desktop: missing Electron sandbox helper: $SANDBOX" >&2
  exit 1
fi
chown root:root "$SANDBOX"
chmod 4755 "$SANDBOX"

# 可选 systemd --user 服务文件：安装到系统目录，方便高级用户用 systemctl 管理
SERVICE_SRC="/opt/wanwei-shuyi-desktop/systemd/wanwei-shuyi-desktop.service"
SERVICE_DST="/etc/systemd/user/wanwei-shuyi-desktop.service"
if [ -f "$SERVICE_SRC" ]; then
  mkdir -p /etc/systemd/user
  install -m 0644 "$SERVICE_SRC" "$SERVICE_DST"
fi

exit 0
