#!/bin/bash
# CodeartsBridge 一键安装脚本
# 用法: ./install.sh [install|uninstall|help]

set -e

REPO_URL="https://github.com/nathanxiangang-web/CodeartsBridge.git"
INSTALL_DIR="${HOME}/codearts-bridge"
PYTHON_MIN="3.10"

print_help() {
    cat << 'EOF'
========================================
  CodeartsBridge 使用说明
========================================

【安装】
  ./install.sh install
  或
  curl -fsSL https://raw.githubusercontent.com/nathanxiangang-web/CodeartsBridge/main/install.sh | bash -s install

  安装内容：
    1. 克隆仓库到 ~/codearts-bridge
    2. 检查 Python >= 3.10
    3. pip install -e . 安装 bridge 命令
    4. 复制示例配置文件（projects.json / workers.json）

【卸载】
  ./install.sh uninstall

  卸载内容：
    1. pip uninstall codex-glm-bridge
    2. 删除 ~/codearts-bridge 目录

【启动 Bridge Server（主节点）】
  bridge serve --host 0.0.0.0 --port 8080

  然后浏览器打开 http://localhost:8080

【启动 Worker Agent（每台 Worker）】
  bridge-worker-agent --listen 0.0.0.0 --port 8765

  或用 systemd：
    sudo cp deploy/bridge-worker-agent.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now bridge-worker-agent

【CLI 命令】
  bridge bootstrap              # 初始化目录结构
  bridge doctor                 # 检查环境和配置
  bridge status                 # 查看所有任务状态
  bridge create -p <项目> -w <Worker> -t <任务ID> -f <任务文件>  # 创建任务
  bridge dispatch               # 派发待执行任务
  bridge run -t <任务ID>        # 执行单个任务
  bridge pipeline               # 运行完整流水线
  bridge serve                  # 启动 Web UI 服务

【Web UI 页面】
  仪表盘    - 在线/空闲/禁用 Worker 统计，任务计数
  项目      - 项目列表，逻辑分组
  任务      - 全部任务列表，状态过滤、搜索
  工作节点  - Worker 卡片：在线状态、当前任务、心跳
  审查      - 已完成任务审查：目标、验收标准、变更文件
  指标      - 遥测指标和统计
  思考回显  - 实时显示 Agent 思考流（SSE 推送）
  设置      - Bridge 配置和健康检查

【配置文件】
  ~/codearts-bridge/projects.json  - 项目配置
  ~/codearts-bridge/workers.json   - 工作节点配置
  ~/codearts-bridge/supervision.json - 监督配置（可选）

【Transport 模式】
  agent  - HTTP API 常驻进程（推荐，无需 SSH）
  ssh    - SSH 远程执行（传统模式）
  local  - 本地执行（开发调试）

【前置条件】
  - Python >= 3.10
  - 各 Worker 已安装 CodeArts CLI 并配置 AK/SK
  - SSH 免密登录（仅 SSH transport 需要）

【更多文档】
  https://github.com/nathanxiangang-web/CodeartsBridge

========================================
EOF
}

check_python() {
    if ! command -v python3 &>/dev/null; then
        echo "[错误] 未找到 python3，请先安装 Python >= ${PYTHON_MIN}"
        exit 1
    fi
    local ver
    ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
        echo "[OK] Python ${ver}"
    else
        echo "[错误] Python ${ver} 版本过低，需要 >= ${PYTHON_MIN}"
        exit 1
    fi
}

do_install() {
    echo "========================================"
    echo "  CodeartsBridge 安装"
    echo "========================================"

    check_python

    # 克隆仓库
    if [ -d "${INSTALL_DIR}" ]; then
        echo "[跳过] ${INSTALL_DIR} 已存在"
    else
        echo "[安装] 克隆仓库到 ${INSTALL_DIR}"
        git clone "${REPO_URL}" "${INSTALL_DIR}"
    fi

    cd "${INSTALL_DIR}"

    # 安装 Python 包
    echo "[安装] pip install -e ."
    pip3 install -e . --quiet

    # 复制示例配置
    if [ ! -f "projects.json" ] && [ -f "projects.example.json" ]; then
        cp projects.example.json projects.json
        echo "[配置] 已创建 projects.json（请编辑填写你的项目信息）"
    fi
    if [ ! -f "workers.json" ] && [ -f "workers.example.json" ]; then
        cp workers.example.json workers.json
        echo "[配置] 已创建 workers.json（请编辑填写你的节点信息）"
    fi

    # 验证安装
    if command -v bridge &>/dev/null; then
        echo ""
        echo "========================================"
        echo "  安装成功！"
        echo "========================================"
        echo ""
        echo "下一步："
        echo "  1. 编辑配置:  ${INSTALL_DIR}/projects.json 和 workers.json"
        echo "  2. 启动 Bridge:  bridge serve --host 0.0.0.0 --port 8080"
        echo "  3. 启动 Worker Agent:  bridge-worker-agent --listen 0.0.0.0 --port 8765"
        echo "  4. 打开浏览器:  http://localhost:8080"
        echo ""
        echo "使用说明:  ./install.sh help"
    else
        echo "[警告] bridge 命令未在 PATH 中找到"
        echo "  请确保 ~/.local/bin 在 PATH 中，或使用:"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
}

do_uninstall() {
    echo "========================================"
    echo "  CodeartsBridge 卸载"
    echo "========================================"

    # 卸载 Python 包
    echo "[卸载] pip uninstall codex-glm-bridge"
    pip3 uninstall -y codex-glm-bridge 2>/dev/null || echo "[跳过] 包未安装"

    # 删除安装目录
    if [ -d "${INSTALL_DIR}" ]; then
        echo "[卸载] 删除 ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    else
        echo "[跳过] ${INSTALL_DIR} 不存在"
    fi

    echo ""
    echo "卸载完成。"
}

# 主入口
case "${1:-help}" in
    install)
        do_install
        ;;
    uninstall)
        do_uninstall
        ;;
    help|--help|-h)
        print_help
        ;;
    *)
        echo "未知命令: $1"
        echo "用法: ./install.sh [install|uninstall|help]"
        exit 1
        ;;
esac
