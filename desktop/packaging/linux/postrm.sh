#!/bin/sh
# postrm — 枢忆·花朝 deb/rpm 卸载后脚本
set -e

# deb 的最终卸载动作是 remove/purge/disappear，rpm 的最终卸载计数是 0；
# upgrade/1 期间必须保留服务文件，避免旧版本 postrm 删除新版本刚安装的副本。
case "${1:-}" in
  remove|purge|disappear|0|"")
    rm -f /etc/systemd/user/wanwei-shuyi-desktop.service
    COMMAND_TARGET="/opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop"
    COMMAND_LINK="/usr/bin/wanwei-shuyi-desktop"
    if [ -L "$COMMAND_LINK" ] &&
       [ "$(readlink "$COMMAND_LINK")" = "$COMMAND_TARGET" ]; then
      rm -f "$COMMAND_LINK"
    fi
    # rpm 在卸载后可能留下空的顶层安装目录；rmdir 只删除空目录，
    # 因而不会误删管理员放入的文件或未来需要保留的数据。
    rmdir /opt/wanwei-shuyi-desktop 2>/dev/null || true
    ;;
esac

if [ -x /usr/bin/update-desktop-database ]; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# 用户数据（~/.config/wanwei-shuyi-desktop）保留，避免误删记忆数据库；
# 如需彻底清理，请用户手动执行：rm -rf ~/.config/wanwei-shuyi-desktop
exit 0
