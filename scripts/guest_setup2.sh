#!/bin/bash
# guest_setup2.sh — 免 apt 的用户态环境准备（麒麟 ostree 防护下可用）
set -e
mkdir -p ~/wanwei ~/opt
cd ~/wanwei

echo "== os =="; cat /etc/os-release | head -2
echo "== arch =="; uname -m
echo "== python =="; python3 --version
python3 -c "import venv; print('VENV_OK')" 2>/dev/null || echo VENV_MISSING

# 用户态安装 Node.js v22.23.2（官方 x64 tarball，不经 apt）
if [ ! -x ~/opt/node-v22/bin/node ]; then
  curl --fail --show-error --location -o node.tar.xz http://10.0.2.2:8000/dl/node-v22.23.2-linux-x64.tar.xz
  tar -xJf node.tar.xz -C ~/opt
  mv ~/opt/node-v22.23.2-linux-x64 ~/opt/node-v22
fi
export PATH="$HOME/opt/node-v22/bin:$PATH"
node -v && npm -v && echo NODE_READY

# 配置 npm 国内镜像（离线/慢网兜底）
npm config set registry https://registry.npmmirror.com
echo SETUP_DONE
