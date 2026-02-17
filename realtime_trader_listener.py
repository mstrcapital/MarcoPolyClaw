"""
WebSocket 实时交易监听器 (Realtime Trader Listener)
=================================================

通过 WebSocket 实时监控链上交易事件
目标: < 100ms 延迟

技术方案:
1. 订阅 Polymarket CLOB WebSocket
2. 监听目标地址的交易
3. 实时推送 Telegram 提醒
"""

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import aiohttp
from dotenv import load_dotenv

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
load_dotenv(CONFIG_DIR / "tradersmonitor.env")

# WebSocket URL
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"

# API
DATA_API = "https://data-api.polymarket.com"

# 配置
MONITORED_WALLETS = os.getenv("MONITORED_WALLETS", "").split(",")
MONITORED_WALLETS = [w.strip().lower() for w in MONITORED_WALLETS if w.strip()]


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class TradeEvent:
    """交易事件"""
    address: str          # 交易地址
    side: str             # BUY/SELL
    outcome: str          # Yes/No
    size: float           # 数量
    price: float          # 价格
    value: float          # 价值
    token_id: str         # Token ID
    market: str           # 市场
    timestamp: datetime


# =============================================================================
# WebSocket 监听器
# =============================================================================

class RealtimeTraderListener:
    """实时交易监听器"""
    
    def __init__(self):
        self.ws = None
        self.is_running = False
        self.reconnect_delay = 5
        self.session = None
    
    async def connect(self):
        """连接 WebSocket"""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(WS_URL)
        print(f"✅ Connected to WebSocket")
        self.reconnect_delay = 5  # 重置重连延迟
    
    async def subscribe_trades(self):
        """订阅所有交易"""
        # 订阅市场交易数据
        subscribe_msg = {
            "type": "subscribe",
            "channel": "trades",
        }
        await self.ws.send_str(json.dumps(subscribe_msg))
        print("📡 Subscribed to trades channel")
    
    async def listen(self):
        """监听消息"""
        async for msg in self.ws:
            if not self.is_running:
                break
            
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await self.process_message(data)
                except Exception as e:
                    print(f"Error processing message: {e}")
            
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"WebSocket error: {self.ws.exception())
                break
    
    async def process_message(self, data: dict):
        """处理消息"""
        msg_type = data.get("type")
        
        if msg_type == "trade":
            trade_data = data.get("data", {})
            self.handle_trade(trade_data)
    
    def handle_trade(self, trade: dict):
        """处理交易事件"""
        # 获取交易者地址 (从 signature 或 order)
        # 注意: WebSocket 数据可能不直接显示地址
        
        # 检查是否为目标地址 (需要额外处理)
        # 目前先打印交易信息
        print(f"Trade: {trade}")
    
    async def start(self):
        """启动监听"""
        self.is_running = True
        
        while self.is_running:
            try:
                await self.connect()
                await self.subscribe_trades()
                await self.listen()
            
            except Exception as e:
                print(f"❌ WebSocket error: {e}")
                print(f"🔄 Reconnecting in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)  # 最多60秒
    
    def stop(self):
        """停止监听"""
        self.is_running = False
        if self.session:
            asyncio.create_task(self.session.close())


# =============================================================================
# 链上事件监听 (更可靠)
# =============================================================================

class ChainListener:
    """链上事件监听器"""
    
    def __init__(self):
        self.is_running = False
    
    async def get_recent_trades(self):
        """获取最近的交易 (轮询)"""
        # 使用 Data API 获取最近的成交
        pass
    
    async def start(self):
        """启动"""
        self.is_running = True
        print("🔗 Chain listener started")


# =============================================================================
# 主函数
# =============================================================================

async def main():
    if not MONITORED_WALLETS:
        print("❌ No wallets to monitor!")
        return
    
    print(f"\n🚀 Realtime Trader Listener")
    print(f"   Monitoring {len(MONITORED_WALLETS)} addresses")
    
    listener = RealtimeTraderListener()
    
    try:
        await listener.start()
    except KeyboardInterrupt:
        listener.stop()
        print("\n🛑 Stopped")


if __name__ == "__main__":
    asyncio.run(main())
