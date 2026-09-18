#!/bin/bash
# CodeartsBridge 一键部署脚本
#
# 用法 1 (交互式):  ./deploy.sh
# 用法 2 (参数式):  ./deploy.sh --workers "192.168.1.51,192.168.1.52" --user nathan --password <密码>
# 用法 3 (环境变量): WORKER_IPS="192.168.1.51,192.168.1.52" WORKER_USER=nathan WORKER_PASS=xxx ./deploy.sh
#
# 前置条件:
#   - Python >= 3.10
#   - git
#   - (可选) sshpass: 如果用密码配置 SSH 免密登录
#   - Worker 机器上已安装 CodeArts CLI (codearts 命令)

set -euo pipefail

REPO_URL="https://github.com/nathanxiangang-web/CodeartsBridge.git"
INSTALL_DIR="${HOME}/bridge-python"
SERVICE_NAME="bridge"
WORKER_IPS="${WORKER_IPS:-}"
WORKER_USER="${WORKER_USER:-nathan}"
WORKER_PASS="${WORKER_PASS:-}"
PROJECT_ROOT="${PROJECT_ROOT:-/home/nathan/bridge-python}"
REMOTE_CLI_PATH="${REMOTE_CLI_PATH:-codearts}"

# ── 颜色 ──────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ── 参数解析 ──────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --workers)   WORKER_IPS="$2"; shift 2 ;;
        --user)      WORKER_USER="$2"; shift 2 ;;
        --password)  WORKER_PASS="$2"; shift 2 ;;
        --repo)      REPO_URL="$2"; shift 2 ;;
        --dir)       INSTALL_DIR="$2"; shift 2 ;;
        --project)   PROJECT_ROOT="$2"; shift 2 ;;
        --help|-h)
            head -12 "$0" | tail -10
            exit 0 ;;
        *) err "未知参数: $1"; exit 1 ;;
    esac
done

echo ""
echo "========================================"
echo "  CodeartsBridge 一键部署"
echo "========================================"
echo ""

# ── 1. 检查 Python ────────────────────────────
if ! command -v python3 &>/dev/null; then
    err "python3 未找到，请先安装 Python >= 3.10"
    exit 1
fi
python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null || {
    err "Python >= 3.10 required (当前: $(python3 --version))"
    exit 1
}
ok "Python $(python3 --version 2>&1)"

# ── 2. 检查 git ───────────────────────────────
command -v git &>/dev/null || { err "git 未找到"; exit 1; }
ok "git $(git --version 2>&1)"

# ── 3. Clone / Update 仓库 ────────────────────
if [ -d "${INSTALL_DIR}/.git" ]; then
    info "仓库已存在，拉取最新..."
    git -C "${INSTALL_DIR}" pull --rebase origin main 2>/dev/null || true
else
    info "克隆仓库到 ${INSTALL_DIR}"
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi
cd "${INSTALL_DIR}"
ok "仓库就绪"

# ── 4. 安装依赖 ───────────────────────────────
info "安装 Python 依赖..."
pip3 install -e . --quiet 2>/dev/null || warn "pip install 失败，将使用 PYTHONPATH=src"
ok "依赖安装完成"

# ── 5. Bootstrap ──────────────────────────────
info "初始化目录结构..."
PYTHONPATH=src python3 -m bridge.cli bootstrap 2>/dev/null || true
ok "Bootstrap 完成"

# ── 6. 配置 SSH 免密登录 ──────────────────────
if [ -n "${WORKER_IPS}" ] && [ -n "${WORKER_PASS}" ]; then
    info "配置 SSH 免密登录到 Worker 节点..."

    if ! command -v sshpass &>/dev/null; then
        warn "sshpass 未安装，尝试安装..."
        sudo apt-get install -y sshpass 2>/dev/null || warn "无法安装 sshpass，请手动配置 SSH 免密"
    fi

    SSH_KEY="${HOME}/.ssh/id_rsa"
    if [ ! -f "${SSH_KEY}" ]; then
        info "生成 SSH 密钥对..."
        ssh-keygen -t rsa -b 2048 -f "${SSH_KEY}" -N "" -q
    fi

    IFS=',' read -ra IPS <<< "${WORKER_IPS}"
    for ip in "${IPS[@]}"; do
        if command -v sshpass &>/dev/null; then
            info "配置免密登录到 ${WORKER_USER}@${ip}..."
            sshpass -p "${WORKER_PASS}" ssh-copy-id \
                -o StrictHostKeyChecking=no \
                "${WORKER_USER}@${ip}" 2>/dev/null && ok "免密登录: ${ip}" || warn "免密配置失败: ${ip}"
        else
            warn "sshpass 不可用，请手动配置免密登录到 ${WORKER_USER}@${ip}"
        fi
    done
fi

# ── 7. 生成 workers.json ──────────────────────
if [ -n "${WORKER_IPS}" ]; then
    info "生成 workers.json..."
    IFS=',' read -ra IPS <<< "${WORKER_IPS}"

    {
        echo '{'
        echo '  "schemaVersion": 1,'
        echo '  "defaults": {'
        echo '    "model": "huaweicloud-maas/GLM-5.2",'
        echo '    "concurrencyLimit": 1,'
        echo '    "enabled": true'
        echo '  },'
        echo '  "workers": ['
        for i in "${!IPS[@]}"; do
            ip="${IPS[$i]}"
            idx=$((i + 1))
            printf '    {\n'
            printf '      "id": "worker-%02d",\n' "${idx}"
            printf '      "transport": "ssh",\n'
            printf '      "host": "%s@%s",\n' "${WORKER_USER}" "${ip}"
            printf '      "cliPath": "%s",\n' "${REMOTE_CLI_PATH}"
            printf '      "model": "huaweicloud-maas/GLM-5.2",\n'
            printf '      "concurrencyLimit": 1,\n'
            printf '      "enabled": true,\n'
            printf '      "capabilities": ["implement", "review", "test"]\n'
            if [ $((i + 1)) -lt ${#IPS[@]} ]; then
                printf '    },\n'
            else
                printf '    }\n'
            fi
        done
        echo '  ]'
        echo '}'
    } > workers.json
    ok "workers.json 已生成 (${#IPS[@]} 个 Worker)"
fi

# ── 8. 生成 projects.json (模板) ──────────────
if [ -n "${WORKER_IPS}" ] && [ ! -f projects.json ]; then
    info "生成 projects.json 模板..."
    IFS=',' read -ra IPS <<< "${WORKER_IPS}"

    {
        echo '{'
        echo '  "schemaVersion": 1,'
        echo '  "defaults": {'
        echo '    "runMode": "auto",'
        echo '    "model": "huaweicloud-maas/GLM-5.2",'
        echo '    "timeoutMinutes": 30'
        echo '  },'
        echo '  "projects": ['
        for i in "${!IPS[@]}"; do
            ip="${IPS[$i]}"
            idx=$((i + 1))
            printf '    {\n'
            printf '      "id": "project-w%02d",\n' "${idx}"
            printf '      "transport": "ssh",\n'
            printf '      "projectRoot": "%s",\n' "${PROJECT_ROOT}"
            printf '      "runMode": "auto",\n'
            printf '      "model": "huaweicloud-maas/GLM-5.2",\n'
            printf '      "timeoutMinutes": 30,\n'
            printf '      "sshHost": "%s@%s",\n' "${WORKER_USER}" "${ip}"
            printf '      "remoteBridgeRoot": "%s",\n' "${PROJECT_ROOT}"
            printf '      "remoteCliPath": "%s"\n' "${REMOTE_CLI_PATH}"
            if [ $((i + 1)) -lt ${#IPS[@]} ]; then
                printf '    },\n'
            else
                printf '    }\n'
            fi
        done
        echo '  ]'
        echo '}'
    } > projects.json
    ok "projects.json 模板已生成 (请根据实际项目修改 projectRoot)"
    warn "请编辑 projects.json 中的 projectRoot 指向你的实际项目路径"
fi

# ── 9. Doctor 检查 ────────────────────────────
echo ""
info "运行 doctor 环境检查..."
PYTHONPATH=src python3 -m bridge.cli doctor 2>&1 || warn "doctor 发现问题，请检查上方输出"

# ── 10. systemd 服务 (root) ───────────────────
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ "$(id -u)" -eq 0 ]; then
    info "安装 systemd 服务..."
    cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=CodeartsBridge Service
After=network.target

[Service]
Type=simple
User=$(stat -c %U "${INSTALL_DIR}")
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONPATH=${INSTALL_DIR}/src
ExecStart=$(which python3) -m bridge.cli serve --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    ok "systemd 服务已安装并启动"
else
    warn "非 root 用户，跳过 systemd 安装"
    echo "  手动安装:"
    echo "    sudo cp ${INSTALL_DIR}/deploy/bridge.service ${SERVICE_FILE}"
    echo "    sudo systemctl daemon-reload && sudo systemctl enable --now ${SERVICE_NAME}"
fi

# ── 11. 验证 ──────────────────────────────────
echo ""
info "验证安装..."
PYTHONPATH=src python3 -m bridge.cli status 2>&1 | head -20 || true

if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    ok "Bridge 服务运行中"
    echo ""
    echo "  API: http://${HOST_IP}:8080/api/health"
    echo "  UI:  http://${HOST_IP}:8080"
fi

# ── 完成 ─────────────────────────────────────
echo ""
echo "========================================"
echo "  部署完成"
echo "========================================"
echo ""
echo "常用命令:"
echo "  PYTHONPATH=src python3 -m bridge.cli status          # 查看任务状态"
echo "  PYTHONPATH=src python3 -m bridge.cli workers         # 查看 Worker 列表"
echo "  PYTHONPATH=src python3 -m bridge.cli projects        # 查看项目列表"
echo "  PYTHONPATH=src python3 -m bridge.cli doctor          # 环境检查"
echo ""
echo "创建并派发任务:"
echo "  PYTHONPATH=src python3 -m bridge.cli create -p <项目ID> -t <任务ID> --task-file task.md"
echo "  PYTHONPATH=src python3 -m bridge.cli auto-dispatch --loop"
echo ""
echo "完整文档: DEPLOY.md"
echo ""
