# 隔离环境镜像

对应 PRD 15.7。

## 构建

镜像构建在 Docker 虚拟机上执行（经 SSH 隧道），构建上下文由 Docker API 传输：

```bash
# 先启动 scripts/docker-tunnel.sh
export DOCKER_HOST=tcp://127.0.0.1:2375   # 必须显式指定，否则会落到本机 Docker Desktop
docker build -t sec-eval-sandbox:latest sandbox
# 或
docker compose -f docker-compose.dev.yml --profile build build sandbox-image
```

虚拟机所在网络无法直连 `deb.debian.org`，Dockerfile 默认将 apt 源替换为 `mirrors.aliyun.com`；在其他网络环境构建时可用 `--build-arg APT_MIRROR=deb.debian.org` 还原。

## 内容

- 基础镜像：`python:3.12-slim`
- 工具：`git`、`ripgrep`、`fd-find`、`curl`、`ping`（iputils-ping）、`procps`、`coreutils`
- 非 root 用户：`sandbox`（uid 1001）
- 预装示例项目依赖：Flask、requests
- 启动命令：`sleep infinity`（由后端通过 `docker exec` 下发命令）

## 运行期约束（由后端创建容器时施加，见 PRD 15.6）

- `--network=none`（默认）
- `--cap-drop=ALL`
- `--security-opt=no-new-privileges`
- `--pids-limit=256`
- `--cpus` / `--memory` 按系统配置
- `--user sandbox`
- 源码卷 `sec-eval-src-{project_id}` 以 `:ro` 挂载至 `/src`
- 工作区卷 `sec-eval-ws-{project_id}-r{run_id}` 以 `:rw` 挂载至 `/workspace`

## 注意

- 镜像内 `/workspace` 必须在 `USER sandbox` 之前创建并 `chown 1001:1001`。空命名卷首次挂载时，Docker 会把镜像内该目录的属主复制进卷；若镜像内是 root，工作区会失去可写权限。
- 源码由后端打包为 tar 流，经 Docker API 写入 `sec-eval-src-{project_id}` 卷；工作区属主由一次性 helper 容器调整为 `1001:1001`。
- 后端不需要 SSH 凭据，只通过 `DOCKER_HOST` 操作虚拟机 Docker；不需要 Windows 绑定挂载。
