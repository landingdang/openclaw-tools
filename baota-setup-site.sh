#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# 宝塔面板自动化配置脚本 - OpenClaw 站点部署
# ============================================================================
# 功能：
#   1. 自动创建站点（绑定域名）
#   2. 申请 Let's Encrypt SSL 证书
#   3. 配置反向代理到 OpenClaw 端口
#   4. 启用 HTTPS 强制跳转
# ============================================================================

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 检查是否为 root 用户
if [[ $EUID -ne 0 ]]; then
   error "此脚本必须以 root 用户运行"
   exit 1
fi

# 检查宝塔是否安装
if [[ ! -f /www/server/panel/BT-Panel ]]; then
    error "未检测到宝塔面板，请先安装宝塔"
    exit 1
fi

# ============================================================================
# 参数解析
# ============================================================================
DOMAIN=""
PORT=""
INSTANCE_DIR=""
FORCE_RECREATE=false

usage() {
    cat << EOF
用法: $0 -d <域名> -p <端口> -i <实例目录> [-f]

参数:
  -d, --domain <域名>        OpenClaw 实例的域名（例如：demo.huxs.cn）
  -p, --port <端口>          OpenClaw 实例的端口（例如：3000）
  -i, --instance <目录>      OpenClaw 实例目录（例如：/root/openclaw-demo）
  -f, --force               强制重新创建站点（删除已存在的站点）
  -h, --help                显示此帮助信息

示例:
  $0 -d demo.huxs.cn -p 3000 -i /root/openclaw-demo
  $0 --domain demo.huxs.cn --port 3000 --instance /root/openclaw-demo --force
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--domain)
            DOMAIN="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -i|--instance)
            INSTANCE_DIR="$2"
            shift 2
            ;;
        -f|--force)
            FORCE_RECREATE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            error "未知参数: $1"
            usage
            ;;
    esac
done

# 验证必需参数
if [[ -z "$DOMAIN" || -z "$PORT" || -z "$INSTANCE_DIR" ]]; then
    error "缺少必需参数"
    usage
fi

# 验证实例目录存在
if [[ ! -d "$INSTANCE_DIR" ]]; then
    error "实例目录不存在: $INSTANCE_DIR"
    exit 1
fi

# 验证端口格式
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 || "$PORT" -gt 65535 ]]; then
    error "无效的端口号: $PORT"
    exit 1
fi

info "配置参数:"
info "  域名: $DOMAIN"
info "  端口: $PORT"
info "  实例目录: $INSTANCE_DIR"
info "  强制重建: $FORCE_RECREATE"
echo

# ============================================================================
# 宝塔 API 调用函数
# ============================================================================
BT_PANEL_PATH="/www/server/panel"
BT_PYTHON="${BT_PANEL_PATH}/pyenv/bin/python"
BT_CLI="${BT_PANEL_PATH}/BT-Panel"

# 调用宝塔 Python API
bt_api_call() {
    local script="$1"
    $BT_PYTHON -c "$script" 2>&1
}

# ============================================================================
# 步骤 1: 检查站点是否已存在
# ============================================================================
info "步骤 1: 检查站点是否已存在..."

SITE_EXISTS=$(bt_api_call "
import sys
sys.path.insert(0, '/www/server/panel/class')
import panelSite
site = panelSite.panelSite()
sites = site.GetSites(None)
if sites and 'data' in sites:
    for s in sites['data']:
        if s.get('name') == '${DOMAIN}':
            print('yes')
            sys.exit(0)
print('no')
" || echo "no")

if [[ "$SITE_EXISTS" == "yes" ]]; then
    if [[ "$FORCE_RECREATE" == true ]]; then
        warn "站点已存在，正在删除..."
        bt_api_call "
import sys
sys.path.insert(0, '/www/server/panel/class')
import panelSite
site = panelSite.panelSite()
class FakeRequest:
    def __init__(self):
        self.form = {'id': '', 'webname': '${DOMAIN}'}
req = FakeRequest()
# 查找站点 ID
sites = site.GetSites(None)
site_id = None
if sites and 'data' in sites:
    for s in sites['data']:
        if s.get('name') == '${DOMAIN}':
            site_id = s.get('id')
            break
if site_id:
    req.form['id'] = str(site_id)
    result = site.DeleteSite(req)
    print(result)
"
        info "站点已删除"
    else
        error "站点已存在: $DOMAIN"
        error "使用 -f 参数强制重新创建"
        exit 1
    fi
fi

# ============================================================================
# 步骤 2: 创建站点
# ============================================================================
info "步骤 2: 创建站点..."

CREATE_RESULT=$(bt_api_call "
import sys
sys.path.insert(0, '/www/server/panel/class')
import panelSite
site = panelSite.panelSite()
class FakeRequest:
    def __init__(self):
        self.form = {
            'webname': '${DOMAIN}',
            'path': '${INSTANCE_DIR}/www',
            'type_id': '0',
            'type': 'PHP',
            'version': '00',
            'port': '80',
            'ps': 'OpenClaw Instance - ${DOMAIN}',
            'ftp': 'false',
            'sql': 'false'
        }
req = FakeRequest()
result = site.AddSite(req)
print(result)
")

if echo "$CREATE_RESULT" | grep -q "success\|成功"; then
    info "站点创建成功"
else
    error "站点创建失败: $CREATE_RESULT"
    exit 1
fi

# 创建 www 目录（如果不存在）
mkdir -p "${INSTANCE_DIR}/www"
echo "OpenClaw Instance" > "${INSTANCE_DIR}/www/index.html"

# ============================================================================
# 步骤 3: 配置反向代理
# ============================================================================
info "步骤 3: 配置反向代理..."

NGINX_CONF="/www/server/panel/vhost/nginx/${DOMAIN}.conf"

if [[ ! -f "$NGINX_CONF" ]]; then
    error "Nginx 配置文件不存在: $NGINX_CONF"
    exit 1
fi

# 备份原配置
cp "$NGINX_CONF" "${NGINX_CONF}.bak"

# 生成反向代理配置
cat > "$NGINX_CONF" << EOF
server {
    listen 80;
    server_name ${DOMAIN};

    # 访问日志
    access_log /www/wwwlogs/${DOMAIN}.log;
    error_log /www/wwwlogs/${DOMAIN}.error.log;

    # 反向代理到 OpenClaw
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # 缓冲设置
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
    }
}
EOF

info "反向代理配置已生成"

# 测试 Nginx 配置
if nginx -t 2>&1 | grep -q "successful"; then
    info "Nginx 配置测试通过"
    systemctl reload nginx
    info "Nginx 已重载"
else
    error "Nginx 配置测试失败"
    mv "${NGINX_CONF}.bak" "$NGINX_CONF"
    error "已恢复原配置"
    exit 1
fi

# ============================================================================
# 步骤 4: 申请 SSL 证书
# ============================================================================
info "步骤 4: 申请 Let's Encrypt SSL 证书..."

# 检查域名是否解析到本机
info "检查域名解析..."
DOMAIN_IP=$(dig +short "$DOMAIN" @8.8.8.8 | tail -1)
LOCAL_IP=$(curl -s ifconfig.me || curl -s icanhazip.com || echo "")

if [[ -z "$DOMAIN_IP" ]]; then
    warn "无法解析域名: $DOMAIN"
    warn "请确保域名已正确解析到本服务器"
    warn "跳过 SSL 证书申请"
else
    info "域名解析: $DOMAIN -> $DOMAIN_IP"
    if [[ "$DOMAIN_IP" != "$LOCAL_IP" ]]; then
        warn "域名未解析到本机 IP: $LOCAL_IP"
        warn "跳过 SSL 证书申请"
    else
        info "域名解析正确，开始申请 SSL 证书..."

        SSL_RESULT=$(bt_api_call "
import sys
sys.path.insert(0, '/www/server/panel/class')
import panelSSL
ssl = panelSSL.panelSSL()
class FakeRequest:
    def __init__(self):
        self.form = {
            'siteName': '${DOMAIN}',
            'domains': '${DOMAIN}',
            'email': 'admin@${DOMAIN}',
            'auth_type': 'http'
        }
req = FakeRequest()
result = ssl.ApplySSL(req)
print(result)
" || echo "failed")

        if echo "$SSL_RESULT" | grep -q "success\|成功"; then
            info "SSL 证书申请成功"

            # 启用 HTTPS 强制跳转
            info "启用 HTTPS 强制跳转..."

            # 更新 Nginx 配置，添加 HTTPS 和强制跳转
            cat > "$NGINX_CONF" << EOF
server {
    listen 80;
    server_name ${DOMAIN};

    # 强制 HTTPS
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    # SSL 证书
    ssl_certificate /www/server/panel/vhost/cert/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /www/server/panel/vhost/cert/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:HIGH:!aNULL:!MD5:!RC4:!DHE;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # 访问日志
    access_log /www/wwwlogs/${DOMAIN}.log;
    error_log /www/wwwlogs/${DOMAIN}.error.log;

    # 反向代理到 OpenClaw
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # 缓冲设置
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
    }
}
EOF

            if nginx -t 2>&1 | grep -q "successful"; then
                systemctl reload nginx
                info "HTTPS 配置已生效"
            else
                warn "HTTPS 配置失败，保持 HTTP 配置"
            fi
        else
            warn "SSL 证书申请失败: $SSL_RESULT"
            warn "站点将以 HTTP 方式运行"
        fi
    fi
fi

# ============================================================================
# 步骤 5: 验证配置
# ============================================================================
info "步骤 5: 验证配置..."

# 检查端口是否监听
if ss -lnt 2>/dev/null | grep -q ":${PORT} " || netstat -lnt 2>/dev/null | grep -q ":${PORT} "; then
    info "OpenClaw 端口 ${PORT} 正在监听"
else
    warn "OpenClaw 端口 ${PORT} 未监听"
    warn "请确保 OpenClaw 容器已启动"
fi

# 测试反向代理
info "测试反向代理..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}" || echo "000")
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "302" || "$HTTP_CODE" == "301" ]]; then
    info "OpenClaw 服务响应正常 (HTTP $HTTP_CODE)"
else
    warn "OpenClaw 服务响应异常 (HTTP $HTTP_CODE)"
fi

# ============================================================================
# 完成
# ============================================================================
echo
info "=========================================="
info "宝塔站点配置完成！"
info "=========================================="
info "域名: $DOMAIN"
info "端口: $PORT"
info "实例目录: $INSTANCE_DIR"
info "Nginx 配置: $NGINX_CONF"
echo
info "访问地址:"
if [[ -f "/www/server/panel/vhost/cert/${DOMAIN}/fullchain.pem" ]]; then
    info "  https://${DOMAIN}"
else
    info "  http://${DOMAIN}"
fi
echo
info "如需修改配置，请编辑: $NGINX_CONF"
info "重载 Nginx: systemctl reload nginx"
echo
