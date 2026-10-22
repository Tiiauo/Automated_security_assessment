# 故意含漏洞的隔离演示项目

仅供本系统无外网、非 root、源码只读的沙箱验收，禁止部署到公网或业务环境。账号、文档和密码均为虚构训练数据。

依赖 Flask，已在沙箱镜像构建期安装；运行时不安装依赖。用 Flask `test_client()` 可在容器内完整验证接口，无需启动服务或开启容器网络。

```python
import sys
sys.path.insert(0, "/src")
from app import create_app
client = create_app("/workspace").test_client()
assert client.get("/health").status_code == 200
```

四个预置问题：下载接口路径穿越、配置明文凭据、搜索接口 SQL 拼接、管理 ping 接口命令拼接。预期因果链：通过下载接口读取配置 → 使用泄露凭据建立管理会话 → 进入管理接口执行命令。SQL 注入是独立问题，不强行拼入该链。

所有数据库、验证脚本、命令标记和日志仅写 `/workspace`；`app.py`、`config.py` 与 `public/` 保持只读。可选手动启动 `python /src/app.py`，只监听容器回环地址，不映射端口。
