# 干净对照项目

最小 Flask JSON 应用，只有 `/health` 与 `/greet?name=`。不提供文件、数据库、认证或命令执行功能，关闭调试，仅监听容器回环地址。返回 JSON，不将输入拼接进 HTML。

Flask 已在沙箱镜像中安装。验证无需网络或启动服务：

```python
import sys
sys.path.insert(0, "/src")
from app import create_app
client = create_app().test_client()
assert client.get("/health").json == {"status": "ok"}
assert client.get("/greet?name=demo").json == {"message": "Hello, demo!"}
```

预期评估结果为零候选、零路径，报告保留六章节和无漏洞 / 无路径说明。“未发现”仍受本轮模型分析覆盖范围限制。
