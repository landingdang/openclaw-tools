#!/bin/bash
#
# OpenClaw Lark 插件安装脚本
# 用途：为已部署的 OpenClaw 实例安装 openclaw-lark 插件
#
# 使用方法：
#   bash install-lark-plugin.sh [实例目录]
#
# 示例：
#   bash install-lark-plugin.sh /data/openclaw/suidaofengyuan
#

set -euo pipefail

# ============================================================
# 颜色输出函数
# ============================================================
red() { echo -e "\033[31m$*\033[0m"; }
green() { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
blue() { echo -e "\033[34m$*\033[0m"; }

# ============================================================
# 配置变量
# ============================================================
LARK_PLUGIN_REPO="https://github.com/landingdang/openclaw-lark.git"
LARK_PLUGIN_BRANCH="main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# 帮助信息
# ============================================================
show_help() {
  cat << EOF
OpenClaw Lark 插件安装脚本

用途：
  为已部署的 OpenClaw 实例安装 openclaw-lark 飞书插件

使用方法：
  bash install-lark-plugin.sh [实例目录]

参数：
  实例目录    OpenClaw 实例的完整路径（可选，不提供则交互式输入）

示例：
  bash install-lark-plugin.sh /data/openclaw/suidaofengyuan
  bash install-lark-plugin.sh

插件功能：
  - 飞书/Lark 消息收发
  - 云文档操作
  - 多维表格管理
  - 日历日程管理
  - 任务管理
  - 交互式卡片和流式回复

注意事项：
  1. 确保实例已成功部署并正在运行
  2. 需要 pnpm 环境（脚本会自动安装）
  3. 需要 Git 环境（用于克隆插件源码）
  4. 插件构建需要 Node.js 22+ 环境

EOF
}

# ============================================================
# 检查依赖
# ============================================================
check_dependencies() {
  local missing_deps=()

  if ! command -v docker &>/dev/null; then
    missing_deps+=("docker")
  fi

  if ! command -v git &>/dev/null; then
    missing_deps+=("git")
  fi

  if [[ ${#missing_deps[@]} -gt 0 ]]; then
    red "错误：缺少必要的依赖工具"
    echo "缺少的工具: ${missing_deps[*]}"
    echo
    echo "请先安装这些工具："
    for dep in "${missing_deps[@]}"; do
      echo "  - $dep"
    done
    exit 1
  fi
}

# ============================================================
# 验证实例目录
# ============================================================
validate_instance_dir() {
  local instance_dir="$1"

  if [[ ! -d "$instance_dir" ]]; then
    red "错误：实例目录不存在: $instance_dir"
    exit 1
  fi

  if [[ ! -f "$instance_dir/compose.yaml" ]]; then
    red "错误：不是有效的 OpenClaw 实例目录（缺少 compose.yaml）"
    exit 1
  fi

  if [[ ! -d "$instance_dir/config" ]]; then
    red "错误：实例配置目录不存在: $instance_dir/config"
    exit 1
  fi

  green "✓ 实例目录验证通过: $instance_dir"
}

# ============================================================
# 检查实例是否运行
# ============================================================
check_instance_running() {
  local instance_dir="$1"

  green "检查实例运行状态..."
  (
    cd "$instance_dir"
    if ! docker compose ps openclaw-gateway | grep -q "Up"; then
      yellow "警告：openclaw-gateway 容器未运行"
      echo "是否启动容器？(y/n)"
      read -r answer
      if [[ "$answer" =~ ^[Yy] ]]; then
        green "启动容器..."
        docker compose up -d openclaw-gateway
        sleep 3
      else
        red "错误：需要容器运行才能安装插件"
        exit 1
      fi
    fi
  )
  green "✓ 实例正在运行"
}

# ============================================================
# 准备插件源码
# ============================================================
prepare_plugin_source() {
  local plugin_dir="$1"

  if [[ -d "$plugin_dir/.git" ]]; then
    green "更新现有插件源码..."
    (
      cd "$plugin_dir"
      if git fetch origin 2>/dev/null; then
        git checkout "$LARK_PLUGIN_BRANCH"
        git pull origin "$LARK_PLUGIN_BRANCH" || {
          yellow "更新失败，使用现有源码"
        }
      else
        yellow "网络连接失败，使用现有源码"
      fi
    )
  elif [[ -d "$plugin_dir" && -f "$plugin_dir/package.json" ]]; then
    green "使用现有插件源码目录"
  else
    green "克隆插件源码..."
    mkdir -p "$(dirname "$plugin_dir")"
    if ! git clone --branch "$LARK_PLUGIN_BRANCH" --single-branch "$LARK_PLUGIN_REPO" "$plugin_dir"; then
      red "错误：克隆插件源码失败"
      echo
      yellow "可能的原因："
      echo "  1. 网络连接问题"
      echo "  2. GitHub 访问受限"
      echo
      yellow "解决方案："
      echo "  1. 检查网络连接后重试"
      echo "  2. 手动下载插件源码到: $plugin_dir"
      exit 1
    fi
  fi

  green "✓ 插件源码准备完成"
}

# ============================================================
# 构建插件包
# ============================================================
build_plugin_package() {
  local plugin_dir="$1"
  local output_dir="$2"

  green "构建插件包..."

  # 检查并安装 pnpm
  if ! command -v pnpm &>/dev/null; then
    yellow "pnpm 未安装，正在安装..."
    npm install -g pnpm --registry=https://registry.npmjs.org/
  fi

  (
    cd "$plugin_dir"

    # 安装依赖
    green "安装插件依赖..."
    pnpm install

    # 构建
    green "构建插件..."
    pnpm run build

    # 打包
    green "打包插件..."
    pnpm pack

    # 移动到输出目录
    mkdir -p "$output_dir"
    # pnpm pack 生成的文件名格式：larksuite-openclaw-lark-2026.4.1.tgz
    if ls larksuite-openclaw-lark-*.tgz 1>/dev/null 2>&1; then
      mv larksuite-openclaw-lark-*.tgz "$output_dir/openclaw-lark.tgz"
    elif ls openclaw-lark-*.tgz 1>/dev/null 2>&1; then
      mv openclaw-lark-*.tgz "$output_dir/openclaw-lark.tgz"
    else
      red "错误：未找到打包文件"
      exit 1
    fi

    green "✓ 插件包已生成: $output_dir/openclaw-lark.tgz"
  )
}

# ============================================================
# 安装插件到实例
# ============================================================
install_plugin_to_instance() {
  local instance_dir="$1"
  local plugin_package="$2"

  green "安装插件到实例..."

  # 创建 extensions 目录
  mkdir -p "$instance_dir/config/extensions"

  # 复制插件包
  cp "$plugin_package" "$instance_dir/config/extensions/"
  green "✓ 插件包已复制到实例"

  # 在容器中安装插件
  green "在容器中安装插件..."
  (
    cd "$instance_dir"
    docker compose run --rm openclaw-cli \
      plugins install /home/node/.openclaw/extensions/openclaw-lark.tgz
  )

  green "✓ 插件安装完成"
}

# ============================================================
# 启用插件
# ============================================================
enable_plugin() {
  local instance_dir="$1"

  green "启用插件..."
  (
    cd "$instance_dir"
    docker compose run --rm openclaw-cli \
      plugins enable openclaw-lark
  )

  green "✓ 插件已启用"
}

# ============================================================
# 验证插件安装
# ============================================================
verify_plugin_installation() {
  local instance_dir="$1"

  green "验证插件安装..."
  (
    cd "$instance_dir"
    if docker compose run --rm openclaw-cli plugins list | grep -q "openclaw-lark"; then
      green "✓ 插件安装验证成功"
      echo
      blue "已安装的插件列表："
      docker compose run --rm openclaw-cli plugins list
    else
      yellow "警告：插件列表中未找到 openclaw-lark"
    fi
  )
}

# ============================================================
# 主函数
# ============================================================
main() {
  # 处理帮助参数
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    show_help
    exit 0
  fi

  echo
  blue "========================================"
  blue "  OpenClaw Lark 插件安装脚本"
  blue "========================================"
  echo

  # 检查依赖
  check_dependencies

  # 获取实例目录
  local instance_dir="${1:-}"
  if [[ -z "$instance_dir" ]]; then
    echo "请输入 OpenClaw 实例目录的完整路径："
    echo "（例如: /data/openclaw/suidaofengyuan）"
    read -r -p "> " instance_dir
    instance_dir="${instance_dir// /}"  # 去除空格
  fi

  # 验证实例目录
  validate_instance_dir "$instance_dir"

  # 检查实例运行状态
  check_instance_running "$instance_dir"

  # 准备工作目录
  local work_dir="$(dirname "$instance_dir")"
  local plugin_source_dir="$work_dir/openclaw-lark-source"
  local plugin_build_dir="$work_dir/openclaw-lark-build"

  echo
  green "安装配置："
  echo "  实例目录: $instance_dir"
  echo "  源码目录: $plugin_source_dir"
  echo "  构建目录: $plugin_build_dir"
  echo "  插件仓库: $LARK_PLUGIN_REPO"
  echo "  插件分支: $LARK_PLUGIN_BRANCH"
  echo

  read -r -p "确认开始安装？(y/n) " confirm
  if [[ ! "$confirm" =~ ^[Yy] ]]; then
    yellow "已取消安装"
    exit 0
  fi

  echo
  green "========== 开始安装 =========="
  echo

  # 步骤 1: 准备插件源码
  green "[1/5] 准备插件源码"
  prepare_plugin_source "$plugin_source_dir"
  echo

  # 步骤 2: 构建插件包
  green "[2/5] 构建插件包"
  build_plugin_package "$plugin_source_dir" "$plugin_build_dir"
  echo

  # 步骤 3: 安装插件
  green "[3/5] 安装插件到实例"
  install_plugin_to_instance "$instance_dir" "$plugin_build_dir/openclaw-lark.tgz"
  echo

  # 步骤 4: 启用插件
  green "[4/5] 启用插件"
  enable_plugin "$instance_dir"
  echo

  # 步骤 5: 验证安装
  green "[5/5] 验证安装"
  verify_plugin_installation "$instance_dir"
  echo

  # 清理构建目录（可选）
  read -r -p "是否清理临时构建目录？(y/n) " cleanup
  if [[ "$cleanup" =~ ^[Yy] ]]; then
    rm -rf "$plugin_build_dir"
    green "✓ 已清理构建目录"
  fi

  echo
  green "=========================================="
  green "  插件安装完成！"
  green "=========================================="
  echo
  echo "后续步骤："
  echo "  1. 访问 OpenClaw 控制台配置飞书机器人"
  echo "  2. 参考文档: https://bytedance.larkoffice.com/docx/MFK7dDFLFoVlOGxWCv5cTXKmnMh"
  echo
}

# 执行主函数
main "$@"
