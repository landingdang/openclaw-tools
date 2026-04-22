# OpenClaw 宝塔面板部署指南

本指南介绍如何使用三个核心脚本在宝塔面板环境下部署和管理 OpenClaw 多实例。

## 目录

- [前置要求](#前置要求)
- [脚本概览](#脚本概览)
- [快速开始](#快速开始)
- [详细使用说明](#详细使用说明)
  - [1. openclaw-instance.sh - 实例部署](#1-openclaw-instancesh---实例部署)
  - [2. openclaw_backup_migrate.sh - 备份迁移](#2-openclaw_backup_migratesh---备份迁移)
  - [3. feishu_bot_creator.py - 飞书机器人](#3-feishu_bot_creatorpy---飞书机器人)
- [常见场景](#常见场景)
- [故障排查](#故障排查)

---

## 前置要求

### 系统环境
- 操作系统：Linux (CentOS/Ubuntu/Debian)
- 宝塔面板：已安装并运行
- Docker：已安装 Docker 和 Docker Compose
- Python：Python 3.7+
- Root 权限：部署脚本需要 root 执行

### 必备命令
```bash
# 检查必备命令是否安装
command -v docker && echo "✓ Docker 已安装"
command -v python3 && echo "✓ Python3 已安装"
command -v curl && echo "✓ curl 已安装"
command -v ss || command -v netstat && echo "✓ 端口检测工具已安装"
```

---

## 脚本概览

| 脚本 | 用途 | 主要功能 |
|------|------|----------|
| `openclaw-instance.sh` | 实例部署管理 | 创建/更新 OpenClaw 实例，配置域名、端口、插件 |
| `openclaw_backup_migrate.sh` | 备份与迁移 | 备份配置和数据，跨服务器迁移 |
| `feishu_bot_creator.py` | 飞书机器人创建 | 自动化创建飞书企业自建机器人 |

---

## 快速开始

### 第一步：部署第一个实例

```bash
# 1. 下载脚本
cd /root
wget https://your-repo/openclaw-instance.sh
chmod +x openclaw-instance.sh

# 2. 运行部署脚本
./openclaw-instance.sh
```

按提示输入：
- 镜像名：`docker.cnb.cool/btpanel/openclaw:latest`
- 基础目录：`/data/openclaw`
- 时区：`Asia/Shanghai`
- 主域名：`yourdomain.com`
- 实例短名：`a`
- 二级域名前缀：`oc1`

### 第二步：配置宝塔站点

1. **添加 DNS 记录**
   ```
   类型: A
   主机记录: oc1
   记录值: 你的服务器IP
   ```

2. **创建宝塔站点**
   - 域名：`oc1.yourdomain.com`
   - 申请 SSL 证书

3. **配置 Nginx 反向代理**
   
   复制脚本生成的配置：
   ```bash
   cat /data/openclaw/a/nginx-oc1.yourdomain.com.conf
   ```
   
   粘贴到宝塔站点的 Nginx 配置中（替换 `location /` 部分）

4. **访问测试**
   ```
   https://oc1.yourdomain.com
   ```

---

## 详细使用说明

## 1. openclaw-instance.sh - 实例部署

### 功能特性

- ✅ 多实例隔离部署
- ✅ 智能端口分配和冲突检测
- ✅ 支持新建和更新实例
- ✅ 自动生成 Nginx 配置
- ✅ 可选安装 openclaw-lark 飞书插件
- ✅ Git 源码管理（可选）

### 基础用法

```bash
# 以 root 身份运行
sudo ./openclaw-instance.sh
```

### 交互式配置说明

#### 1. 基础配置
```
镜像名: docker.cnb.cool/btpanel/openclaw:latest
  - 使用远程镜像（推荐）
  - 或本地构建的镜像名

基础部署目录: /data/openclaw
  - 所有实例的根目录
  - 必须是绝对路径

时区: Asia/Shanghai
  - 容器内时区设置

主域名: yourdomain.com
  - 用于生成二级域名
```

#### 2. 源码管理选项
```
1) 使用 Docker 镜像内置源码（默认，推荐）
2) 使用 Git 仓库源码（共享源码，节省空间）
```

**选择 1（推荐）**：直接使用镜像内置代码，简单快速

**选择 2**：适合需要自定义源码或多实例共享源码的场景
- Git 仓库地址：`https://github.com/openclaw/openclaw.git`
- Git 分支：`main`
- 源码位置：`/data/openclaw/shared-source`

#### 3. 实例配置

**实例短名**
```
示例: a, b, c, prod, test
规则: 仅允许字母、数字、下划线、中划线
用途: 目录名和项目名前缀
```

**域名配置**

新建实例：
```
二级域名前缀: oc1
规则: 仅小写字母、数字、中划线
生成域名: oc1.yourdomain.com
```

更新实例：
```
域名: oc1.yourdomain.com (可修改)
注意: 修改域名会删除旧的 nginx 配置文件
```

**端口配置**

脚本会自动扫描已用端口并推荐可用端口：
```
UI 端口: 28089 (自动推荐)
  - 映射到容器的 18789 端口
  - 用于 Web 界面访问

桥接端口: 29089 (自动推荐)
  - 映射到容器的 18790 端口
  - 用于设备连接
```

#### 4. 插件安装（可选）

仅在新建实例时询问：
```
是否安装 openclaw-lark 插件? [y/N]
  - openclaw-lark 提供飞书机器人集成
  - 需要 pnpm 和 Node.js 环境
  - 安装后可在容器中管理插件
```

#### 5. 确认部署

```
请确认本次只会新增这个实例：
操作模式   : 新建实例
实例短名   : a
项目名     : openclaw-a
实例目录   : /data/openclaw/a
镜像       : docker.cnb.cool/btpanel/openclaw:latest
时区       : Asia/Shanghai
域名       : oc1.yourdomain.com
UI端口     : 127.0.0.1:28089 -> 18789
桥接端口   : 127.0.0.1:29089 -> 18790

确认开始部署? [Y/n]: y
最终确认：请输入 ADD a
> ADD a
```

### 部署流程

脚本执行 10 个步骤：

```
[1/10] 跳过 Git 源码同步（使用镜像内置源码）
[2/10] 检查本地镜像
[3/10] 创建实例目录
[4/10] 生成 compose.yaml
[5/10] 校验 compose
[6/10] 执行 onboard
[7/10] 写入 gateway 配置
[8/10] 启动 openclaw-gateway
[8.5/10] 安装 openclaw-lark 插件（如果选择）
[9/10] 生成辅助文件
[10/10] 等待健康检查
```

### 生成的文件结构

```
/data/openclaw/
├── a/                              # 实例目录
│   ├── compose.yaml                # Docker Compose 配置
│   ├── instance.env                # 实例元数据
│   ├── nginx-oc1.yourdomain.com.conf  # Nginx 配置片段
│   ├── README-BT.txt               # 运维说明
│   ├── config/                     # OpenClaw 配置目录
│   │   └── openclaw.json
│   └── workspace/                  # 工作空间目录
└── shared-source/                  # Git 源码（如果使用）
```

### 更新现有实例

```bash
# 运行脚本，输入已存在的实例短名
./openclaw-instance.sh

实例短名: a

检测到现有实例：/data/openclaw/a
  现有 UI 端口: 28089
  现有桥接端口: 29089
  现有域名: oc1.yourdomain.com

是否更新此实例的配置? [Y/n]: y
```

更新模式特点：
- 保留 `config/` 和 `workspace/` 数据
- 可修改域名和端口
- 自动重启容器应用新配置
- 不会重新执行 onboard

### 常用运维命令

```bash
# 进入实例目录
cd /data/openclaw/a

# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f openclaw-gateway

# 重启容器
docker compose restart openclaw-gateway

# 停止容器
docker compose down

# 启动容器
docker compose up -d

# 进入 CLI
docker compose run --rm openclaw-cli dashboard --no-open

# 设备管理
docker compose run --rm openclaw-cli devices list
docker compose run --rm openclaw-cli devices approve <requestId>

# 插件管理
docker compose run --rm openclaw-cli plugins list
docker compose run --rm openclaw-cli plugins enable openclaw-lark
docker compose run --rm openclaw-cli plugins disable openclaw-lark
```

### 查看已部署实例

脚本启动时会自动列出所有实例：

```
当前已发现的实例：
短名       项目名               UI端口     桥接端口   域名
----       ------               ------     --------   ----
a          openclaw-a           28089      29089      oc1.yourdomain.com
b          openclaw-b           28090      29090      oc2.yourdomain.com
```

---

## 2. openclaw_backup_migrate.sh - 备份迁移

### 功能特性

- ✅ 完整备份 OpenClaw 状态目录
- ✅ 自动发现和备份外部工作空间
- ✅ 支持跨服务器迁移
- ✅ 自动重写工作空间路径
- ✅ 归档验证和完整性检查

### 备份操作

#### 基础备份

```bash
# 备份默认配置 (~/.openclaw)
./openclaw_backup_migrate.sh backup

# 输出示例
# [openclaw_backup_migrate.sh] 开始创建备份...
# [##################################################] 100% 备份完成
# [openclaw_backup_migrate.sh] 备份已创建: /root/20260422T083015Z-openclaw-backup.tar.gz
```

#### 指定输出路径

```bash
# 输出到指定目录
./openclaw_backup_migrate.sh backup --output /backup/

# 输出到指定文件名
./openclaw_backup_migrate.sh backup --output /backup/my-backup.tar.gz
```

#### 备份特定实例

```bash
# 备份指定状态目录
./openclaw_backup_migrate.sh backup --state-dir /data/openclaw/a/config

# 使用 profile 名称
./openclaw_backup_migrate.sh backup --profile production
```

#### 高级选项

```bash
# 跳过外部工作空间
./openclaw_backup_migrate.sh backup --no-include-workspace

# 备份前不停止 gateway
./openclaw_backup_migrate.sh backup --no-stop-gateway

# 备份后验证归档
./openclaw_backup_migrate.sh backup --verify

# 仅查看备份计划（不实际执行）
./openclaw_backup_migrate.sh backup --dry-run
```

### 验证备份

```bash
# 验证归档文件完整性
./openclaw_backup_migrate.sh verify --archive /backup/20260422T083015Z-openclaw-backup.tar.gz

# 输出示例
# [openclaw_backup_migrate.sh] 验证归档文件...
# 验证通过
```

### 恢复操作

#### 基础恢复

```bash
# 恢复到默认位置 (~/.openclaw)
./openclaw_backup_migrate.sh restore --archive /backup/20260422T083015Z-openclaw-backup.tar.gz

# 输出示例
# [openclaw_backup_migrate.sh] 开始恢复备份...
# [##################################################] 100% 恢复完成
# [openclaw_backup_migrate.sh] 恢复完成: /root/.openclaw
```

#### 恢复到指定位置

```bash
# 恢复到新的状态目录
./openclaw_backup_migrate.sh restore \
  --archive /backup/20260422T083015Z-openclaw-backup.tar.gz \
  --state-dir /data/openclaw/b/config

# 使用 profile 名称
./openclaw_backup_migrate.sh restore \
  --archive /backup/20260422T083015Z-openclaw-backup.tar.gz \
  --profile production
```

#### 覆盖现有实例

```bash
# 覆盖已存在的目录（会先备份旧目录）
./openclaw_backup_migrate.sh restore \
  --archive /backup/20260422T083015Z-openclaw-backup.tar.gz \
  --state-dir /data/openclaw/a/config \
  --overwrite
```

#### 自定义工作空间位置

```bash
# 指定工作空间恢复位置
./openclaw_backup_migrate.sh restore \
  --archive /backup/20260422T083015Z-openclaw-backup.tar.gz \
  --workspace-root /data/workspaces
```

#### 跳过自动操作

```bash
# 恢复后不运行 openclaw doctor
./openclaw_backup_migrate.sh restore \
  --archive /backup/backup.tar.gz \
  --skip-doctor

# 恢复后不重启 gateway
./openclaw_backup_migrate.sh restore \
  --archive /backup/backup.tar.gz \
  --skip-restart

# 仅查看恢复计划（不实际执行）
./openclaw_backup_migrate.sh restore \
  --archive /backup/backup.tar.gz \
  --dry-run
```

### 备份内容说明

备份归档包含：

```
backup.tar.gz
├── manifest.json                   # 备份清单
├── state/                          # 状态目录
│   └── .openclaw/
│       ├── openclaw.json           # 配置文件
│       ├── agents/                 # Agent 配置
│       ├── devices/                # 设备信息
│       └── ...
├── config/                         # 外部配置文件（如果有）
│   └── openclaw.json
└── workspaces/                     # 外部工作空间
    ├── project-a/
    └── project-b/
```

### 跨服务器迁移示例

#### 场景：从服务器 A 迁移到服务器 B

**服务器 A（源服务器）**

```bash
# 1. 备份实例
./openclaw_backup_migrate.sh backup \
  --state-dir /data/openclaw/a/config \
  --output /tmp/migration-backup.tar.gz \
  --verify

# 2. 传输到服务器 B
scp /tmp/migration-backup.tar.gz root@server-b:/tmp/
```

**服务器 B（目标服务器）**

```bash
# 3. 恢复实例
./openclaw_backup_migrate.sh restore \
  --archive /tmp/migration-backup.tar.gz \
  --state-dir /data/openclaw/a/config \
  --workspace-root /data/openclaw/a/workspace

# 4. 启动容器
cd /data/openclaw/a
docker compose up -d
```

---

## 3. feishu_bot_creator.py - 飞书机器人

### 功能特性

- ✅ 自动化创建飞书企业自建机器人
- ✅ 支持飞书（国内版）和 Lark（海外版）
- ✅ 二维码扫码登录
- ✅ 自动配置机器人权限和回调
- ✅ 无需手动操作浏览器

### 安装依赖

```bash
# 初始化并安装依赖（首次使用必须执行）
python3 feishu_bot_creator.py init

# 脚本会自动安装：
# - playwright (浏览器自动化)
# - qrcode (二维码生成)
# - Chromium 浏览器
```

### 创建飞书机器人

#### 基础用法（飞书国内版）

```bash
python3 feishu_bot_creator.py create
```

执行流程：
1. 显示二维码（终端）
2. 使用飞书 App 扫码登录
3. 自动创建机器人应用
4. 配置权限和回调地址
5. 输出 App ID 和 App Secret

#### 创建 Lark 机器人（海外版）

```bash
python3 feishu_bot_creator.py create --platform lark
```

#### 重置浏览器配置

```bash
# 清除登录状态后重新创建
python3 feishu_bot_creator.py create --reset-profile
```

### 配置说明

脚本会在当前目录生成配置文件：

```
feishu_bot_config.json
```

配置内容示例：

```json
{
  "app_id": "cli_a1b2c3d4e5f6g7h8",
  "app_secret": "abcdefghijklmnopqrstuvwxyz123456",
  "verification_token": "token123456",
  "encrypt_key": "encrypt123456",
  "bot_name": "OpenClaw Bot",
  "callback_url": "https://oc1.yourdomain.com/api/feishu/callback"
}
```

### 清理残留进程

```bash
# 关闭残留的浏览器进程
python3 feishu_bot_creator.py cleanup
```

### 测试功能

```bash
# 仅验证配置文件读写（不登录）
python3 feishu_bot_creator.py config-test

# 运行完整回归测试
python3 feishu_bot_creator.py regression-test
```

### 与 openclaw-lark 插件集成

创建机器人后，需要在 OpenClaw 中配置：

```bash
# 1. 进入实例目录
cd /data/openclaw/a

# 2. 配置飞书机器人信息
docker compose run --rm openclaw-cli config set \
  lark.appId "cli_a1b2c3d4e5f6g7h8" \
  lark.appSecret "abcdefghijklmnopqrstuvwxyz123456"

# 3. 重启容器
docker compose restart openclaw-gateway

# 4. 验证插件状态
docker compose run --rm openclaw-cli plugins list
```

### 常见问题

**Q: 二维码显示不完整？**
```bash
# 调整终端窗口大小，确保足够宽度
# 或使用图片查看器打开生成的二维码图片
```

**Q: 扫码后无响应？**
```bash
# 1. 检查网络连接
# 2. 清理浏览器配置重试
python3 feishu_bot_creator.py create --reset-profile
```

**Q: 权限配置失败？**
```bash
# 手动登录飞书开放平台补充配置
# https://open.feishu.cn/app
```

---

## 常见场景

### 场景 1：部署多个独立实例

```bash
# 实例 A - 生产环境
./openclaw-instance.sh
# 短名: prod, 域名前缀: oc-prod

# 实例 B - 测试环境
./openclaw-instance.sh
# 短名: test, 域名前缀: oc-test

# 实例 C - 开发环境
./openclaw-instance.sh
# 短名: dev, 域名前缀: oc-dev
```

### 场景 2：定期备份

```bash
# 创建备份脚本
cat > /root/backup-openclaw.sh <<'EOF'
#!/bin/bash
BACKUP_DIR="/backup/openclaw"
mkdir -p "$BACKUP_DIR"

# 备份所有实例
for instance in /data/openclaw/*/config; do
  name=$(basename $(dirname "$instance"))
  /root/openclaw_backup_migrate.sh backup \
    --state-dir "$instance" \
    --output "$BACKUP_DIR/" \
    --verify
done

# 清理 30 天前的备份
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
EOF

chmod +x /root/backup-openclaw.sh

# 添加到 crontab（每天凌晨 2 点执行）
echo "0 2 * * * /root/backup-openclaw.sh" | crontab -
```

### 场景 3：克隆实例

```bash
# 1. 备份源实例
./openclaw_backup_migrate.sh backup \
  --state-dir /data/openclaw/a/config \
  --output /tmp/clone.tar.gz

# 2. 创建新实例目录
./openclaw-instance.sh
# 短名: b, 域名前缀: oc2

# 3. 恢复到新实例
./openclaw_backup_migrate.sh restore \
  --archive /tmp/clone.tar.gz \
  --state-dir /data/openclaw/b/config \
  --overwrite

# 4. 重启新实例
cd /data/openclaw/b
docker compose restart
```

### 场景 4：批量部署飞书机器人

```bash
# 为每个实例创建独立的飞书机器人
for instance in prod test dev; do
  echo "创建 $instance 实例的飞书机器人..."
  python3 feishu_bot_creator.py create
  mv feishu_bot_config.json /data/openclaw/$instance/feishu_config.json
done
```

---

## 故障排查

### 部署问题

**问题：端口冲突**
```bash
# 检查端口占用
ss -tlnp | grep :28089

# 手动指定其他端口
# 在脚本交互中输入未被占用的端口
```

**问题：镜像拉取失败**
```bash
# 检查 Docker 镜像
docker images | grep openclaw

# 手动拉取镜像
docker pull docker.cnb.cool/btpanel/openclaw:latest

# 或使用本地构建
cd /path/to/openclaw-source
docker build -t openclaw:local .
```

**问题：容器启动失败**
```bash
# 查看容器日志
cd /data/openclaw/a
docker compose logs openclaw-gateway

# 检查配置文件
docker compose config

# 重新执行 onboard
docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js onboard --mode local --no-install-daemon
```

### 备份恢复问题

**问题：备份文件损坏**
```bash
# 验证备份完整性
./openclaw_backup_migrate.sh verify --archive /backup/backup.tar.gz

# 查看备份内容
tar -tzf /backup/backup.tar.gz | head -20
```

**问题：恢复后路径错误**
```bash
# 检查配置文件中的路径
cat /data/openclaw/a/config/openclaw.json | grep workspace

# 手动修正路径
docker compose run --rm openclaw-cli config set \
  agents.list[0].workspace "/data/openclaw/a/workspace/project"
```

### 飞书机器人问题

**问题：依赖安装失败**
```bash
# 手动安装依赖
pip3 install playwright qrcode --break-system-packages
python3 -m playwright install chromium

# 安装系统依赖（CentOS）
yum install -y nss libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1
```

**问题：浏览器启动失败**
```bash
# 检查 Chromium 路径
python3 -c "from playwright.sync_api import sync_playwright; pw = sync_playwright().start(); print(pw.chromium.executable_path); pw.stop()"

# 清理浏览器缓存
rm -rf ~/.cache/ms-playwright
python3 -m playwright install chromium
```

### 网络问题

**问题：无法访问域名**
```bash
# 1. 检查 DNS 解析
nslookup oc1.yourdomain.com

# 2. 检查 Nginx 配置
nginx -t

# 3. 检查容器端口映射
docker compose ps
curl http://127.0.0.1:28089/healthz

# 4. 检查防火墙
firewall-cmd --list-ports
```

**问题：SSL 证书问题**
```bash
# 在宝塔面板重新申请 SSL 证书
# 或使用 Let's Encrypt
certbot --nginx -d oc1.yourdomain.com
```

### 权限问题

**问题：文件权限错误**
```bash
# 修正目录权限（容器使用 uid 1000）
chown -R 1000:1000 /data/openclaw/a/config
chown -R 1000:1000 /data/openclaw/a/workspace
```

**问题：Docker 权限不足**
```bash
# 确保当前用户在 docker 组
usermod -aG docker $USER

# 或使用 root 执行
sudo ./openclaw-instance.sh
```

---

## 附录

### 目录结构参考

```
/data/openclaw/
├── a/                                    # 实例 A
│   ├── compose.yaml
│   ├── instance.env
│   ├── nginx-oc1.yourdomain.com.conf
│   ├── README-BT.txt
│   ├── config/
│   │   ├── openclaw.json
│   │   ├── agents/
│   │   ├── devices/
│   │   └── extensions/
│   │       └── openclaw-lark.tgz
│   └── workspace/
│       └── projects/
├── b/                                    # 实例 B
│   └── ...
└── shared-source/                        # Git 源码（可选）
    ├── .git/
    ├── src/
    └── Dockerfile
```

### 环境变量参考

```bash
# OpenClaw 状态目录
export OPENCLAW_STATE_DIR=/data/openclaw/a/config

# OpenClaw 配置文件
export OPENCLAW_CONFIG_PATH=/data/openclaw/a/config/openclaw.json

# Playwright 浏览器路径
export PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
```

### 相关链接

- OpenClaw 官方文档：https://docs.openclaw.com
- 飞书开放平台：https://open.feishu.cn
- Lark 开放平台：https://open.larksuite.com
- Docker Compose 文档：https://docs.docker.com/compose
- 宝塔面板：https://www.bt.cn

---

## 更新日志

- 2026-04-22：初始版本
  - 添加 openclaw-instance.sh 部署脚本
  - 添加 openclaw_backup_migrate.sh 备份脚本
  - 添加 feishu_bot_creator.py 飞书机器人脚本
  - 完善宝塔面板集成说明
