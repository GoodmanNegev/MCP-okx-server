# MCP-okx-server

## 简介
本项目为 OKX 交易所的 MCP 服务端示例，基于 FastMCP 框架实现，支持账户余额、行情、K线查询及下单等功能。
请在使用前配置key.env中的API密钥信息

## 环境准备
1. 安装 [uv](https://github.com/astral-sh/uv)：

```bash
pip install uv
```

2. 克隆本仓库并进入目录：

```bash
git clone https://github.com/GoodmanNegev/MCP-okx-server.git
cd MCP-okx-server
```

3. 新建 `requirements.txt`，内容示例：

```txt
httpx
python-dotenv
mcp-server
pydantic
```

4. 安装依赖：

```bash
uv pip install -r requirements.txt
```

5. 配置环境变量：

复制 `key.env`，填写 OKX API_KEY、SECRET_KEY、PASSPHRASE。

## 启动服务

```bash
uv pip install -r requirements.txt  # 确保依赖已安装
python main.py run
```

## 调试方式

推荐使用 mcp 工具进行开发调试：

```bash
pip install mcp[cli]
```

```bash
mcp dev main.py
```

在调试页面选择sse，端口号配置为8000  （即main.py运行的端口）
使用session token ，connect成功后
在tools 标签页进行调试


## 主要 MCP 工具
- get_balance：查询账户余额
- get_ticker：查询行情
- get_kline：查询K线
- create_order：下单

---
如需自定义依赖，请编辑 requirements.txt 并重新执行 `uv pip install -r requirements.txt`。