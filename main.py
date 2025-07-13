import os
import hmac
import base64
import json
import asyncio
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv, dotenv_values
from mcp.server import FastMCP
from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context


# 加载环境变量
load_dotenv("key.env")

# --- 配置 ---
env = dotenv_values("key.env")
API_KEY = env.get("API_KEY")
API_SECRET = env.get("SECRET_KEY")
API_PASSPHRASE = env.get("PASSPHRASE")
BASE_URL = env.get("API_BASE", "https://www.okx.com")

# --- MCP 服务初始化 ---
app = FastMCP('okx-trader')

# --- OKX API 签名工具 ---
async def get_okx_server_time() -> str:
    """
    获取 OKX 服务器时间戳，返回格式如 '2024-06-07T12:34:56.789Z'
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/v5/public/time")
        resp.raise_for_status()
        ts = resp.json()['data'][0]['ts']
        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
        return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

def get_okx_signature(timestamp: str, method: str, request_path: str, body: str = ''):
    if not API_SECRET:
        raise ValueError("API_SECRET not found in environment variables.")
    message = timestamp + method.upper() + request_path + body
    mac = hmac.new(bytes(API_SECRET, 'utf-8'), bytes(message, 'utf-8'), digestmod='sha256')
    return base64.b64encode(mac.digest()).decode()

async def get_okx_headers(method: str, request_path: str, body: str = '', timestamp: str = None):
    if not API_KEY or not API_PASSPHRASE:
        raise ValueError("API_KEY or API_PASSPHRASE not found in environment variables.")
    if not timestamp:
        timestamp = await get_okx_server_time()
    signature = get_okx_signature(timestamp, method, request_path, body)
    return {
        'Content-Type': 'application/json',
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'x-simulated-trading': '0' # 模拟盘，正式盘请移除或设为'0'
    }

# --- MCP 工具定义 ---
@app.tool()
async def get_balance() -> str:
    """
    查询账户余额信息。
    返回：包含余额信息的JSON字符串。
    """
    request_path = '/api/v5/account/balance'
    timestamp = await get_okx_server_time()
    headers = await get_okx_headers('GET', request_path, timestamp=timestamp)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}{request_path}", headers=headers)
        response.raise_for_status()
        return json.dumps(response.json(), indent=2)

@app.tool()
async def get_ticker(instId: str) -> str:
    """
    查询特定交易对的市场行情数据。
    参数：instId 交易对ID, 例如 "BTC-USDT"。
    返回：包含市场行情数据的JSON字符串。
    """
    request_path = f'/api/v5/market/ticker?instId={instId}'
    timestamp = await get_okx_server_time()
    headers = await get_okx_headers('GET', request_path, timestamp=timestamp)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}{request_path}", headers=headers)
        response.raise_for_status()
        return json.dumps(response.json(), indent=2)

@app.tool()
async def get_kline(instId: str, bar: str = '1H') -> str:
    """
    查询K线数据。
    参数：instId 交易对ID, 例如 "BTC-USDT"。bar K线周期，默认'1H'。
    返回：包含K线数据的JSON字符串。
    """
    request_path = f'/api/v5/market/candles?instId={instId}&bar={bar}'
    timestamp = await get_okx_server_time()
    headers = await get_okx_headers('GET', request_path, timestamp=timestamp)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}{request_path}", headers=headers)
        response.raise_for_status()
        return json.dumps(response.json(), indent=2)

class OrderElicitation(BaseModel):
    """用于下单时引导用户补充信息或确认操作。"""
    tryAgain: bool = Field(description="余额不足，是否尝试下单更小的数量？")
    newSize: str = Field(default="0.001", description="新的下单数量（字符串，单位与原sz一致）")

@app.tool()
async def create_order(instId: str, side: str, sz: str, ordType: str = 'market', tdMode: str = 'cash', ctx: Context = None) -> str:
    """
    创建现货交易订单，若余额不足则引导用户补充信息。
    参数：instId 交易对ID, side 订单方向, sz 委托数量, ordType 订单类型, tdMode 交易模式。
    返回：包含订单结果的JSON字符串。
    """
    # 下单前先查余额
    request_path_balance = '/api/v5/account/balance'
    timestamp_balance = await get_okx_server_time()
    headers_balance = await get_okx_headers('GET', request_path_balance, timestamp=timestamp_balance)
    async with httpx.AsyncClient() as client:
        resp_balance = await client.get(f"{BASE_URL}{request_path_balance}", headers=headers_balance)
        resp_balance.raise_for_status()
        balance_data = resp_balance.json()
    # 简单判断：假设买单时用USDT余额，卖单时用币余额
    # 实际业务可根据instId和side更精细判断
    base_ccy, quote_ccy = instId.split('-')
    ccy = quote_ccy if side == 'buy' else base_ccy
    available = 0.0
    for acc in balance_data.get('data', [{}])[0].get('details', []):
        if acc.get('ccy') == ccy:
            available = float(acc.get('availBal', 0))
            break
    # 这里只做简单数量判断，实际可结合市价等
    if float(sz) > available:
        if ctx is not None:
            result = await ctx.elicit(
                message=f"当前{ccy}可用余额为{available}，下单数量{sz}超出余额，是否尝试更小的数量？",
                schema=OrderElicitation,
            )
            if result.action == "accept" and result.data and result.data.tryAgain:
                sz = result.data.newSize
            else:
                return "[CANCELLED] 余额不足，订单已取消"
        else:
            return f"[FAILED] 余额不足，可用{ccy}为{available}"
    # 正常下单
    request_path = '/api/v5/trade/order'
    body_dict = {
        "instId": instId,
        "tdMode": tdMode,
        "side": side,
        "ordType": ordType,
        "sz": sz
    }
    body_str = json.dumps(body_dict)
    timestamp = await get_okx_server_time()
    headers = await get_okx_headers('POST', request_path, body=body_str, timestamp=timestamp)
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}{request_path}", headers=headers, content=body_str)
        response.raise_for_status()
        return json.dumps(response.json(), indent=2)

# --- 主程序入口 ---
def main():
    print("Hello from mcp-server-demo!\n可用MCP工具：get_balance, get_ticker, get_kline, create_order")
    print("API_KEY:", API_KEY)
    print("API_SECRET:", API_SECRET)
    print("API_PASSPHRASE:", API_PASSPHRASE)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'run':
        print("Starting OKX MCP Server via SSE...")
        print("Hello from mcp-server-demo!\n可用MCP工具：get_balance, get_ticker, get_kline, create_order")
        print("API_KEY:", API_KEY)
        print("API_SECRET:", API_SECRET)
        print("API_PASSPHRASE:", API_PASSPHRASE)
        app.run(transport='sse')
    else:
        main()
