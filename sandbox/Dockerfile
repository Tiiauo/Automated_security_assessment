FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 虚拟机所在网络无法直连 deb.debian.org（Fastly），默认改用阿里云镜像源；
# 其他网络环境可用 --build-arg APT_MIRROR=deb.debian.org 还原。
ARG APT_MIRROR=mirrors.aliyun.com
RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ripgrep \
        fd-find \
        curl \
        iputils-ping \
        procps \
        coreutils \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 示例项目依赖在构建期安装；运行期容器默认无外网（--network=none）
RUN pip install --no-cache-dir \
        "flask>=3.0,<4" \
        "requests>=2.32,<3"

RUN useradd --create-home --uid 1001 --shell /bin/bash sandbox \
    && mkdir -p /workspace \
    && chown 1001:1001 /workspace

WORKDIR /workspace
USER sandbox

CMD ["sleep", "infinity"]
