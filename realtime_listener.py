"""
实时市场监听器 (Phase 1)
=========================

功能:
- WebSocket 实时订阅 Polymarket 市场数据
- 本地维护 Orderbook 快照
- 盘口深度分析
- 实时套利机会检测

架构:
- WebSocketClient: WebSocket 连接管理
- OrderBook: 订单簿快照维护
- MarketListener: 市场数据监听
- ArbitrageDetector: 实时套利检测
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional
import websockets
from loguru import logger

from config import GAMMA_API, CLOB_API

# =============================================================================
# 配置
# =============================================================================

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# 订阅配置
SUBSCRIBE_TIMEOUT = 30  # 秒
RECONNECT_DELAY = 5    # 重连延迟
HEARTBEAT_INTERVAL = 30 # 心跳间隔

# Orderbook 配置
MAX_ORDERBOOK_DEPTH = 10  # 订单簿深度

# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class Order:
    """订单"""
    price: float
    size: float

@dataclass
class OrderBook:
    """订单簿快照"""
    market_id: str
    token_id: str
    bids: list[Order] = field(default_factory=list)  # 买单 (卖方)
    asks: list[Order] = field(default_factory=list)  # 卖单 (买方)
    last_update: datetime = field(default_factory=datetime.now)
    
    @property
    def best_bid(self) -> float:
        """最佳买价 (highest bid)"""
        return self.bids[0].price if self.bids else 0
    
    @property
    def best_ask(self) -> float:
        """最佳卖价 (lowest ask)"""
        return self.asks[0].price if self.asks else 0
    
    @property
    def spread(self) -> float:
        """买卖价差"""
        return self.best_ask - self.best_bid if self.best_bid and self.best_ask else 0
    
    @property
    def spread_pct(self) -> float:
        """价差百分比"""
        if self.best_bid > 0:
            return (self.spread / self.best_bid) * 100
        return 0
    
    def mid_price(self) -> float:
        """中间价"""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return 0
    
    def depth(self, levels: int = 5) -> Dict:
        """计算深度"""
        bid_depth = sum(o.size for o in self.bids[:levels])
        ask_depth = sum(o.size for o in self.asks[:levels])
        return {
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "total_depth": bid_depth + ask_depth,
            "imbalance": bid_depth / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0.5
        }

@dataclass
class MarketTick:
    """市场数据更新"""
    market_id: str
    token_id: str
    price: float
    size: float
    side: str  # BUY or SELL
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class ArbitrageSignal:
    """实时套利信号"""
    market_id: str
    token_id_1: str
    token_id_2: str
    bid_price: float
    ask_price: float
    spread: float
    spread_pct: float
    depth: Dict
    timestamp: datetime = field(default_factory=datetime.now)

# =============================================================================
# WebSocket 客户端
# =============================================================================

class WSClient:
    """WebSocket 客户端"""
    
    def __init__(self, url: str = WS_URL):
        self.url = url
        self.ws = None
        self._running = False
        self._reconnect_count = 0
        self._subscriptions = set()
    
    async def connect(self) -> bool:
        """连接 WebSocket"""
        try:
            self.ws = await websockets.connect(self.url, ping_interval=HEARTBEAT_INTERVAL)
            self._running = True
            self._reconnect_count = 0
            logger.info(f"✅ WebSocket 已连接: {self.url}")
            return True
        except Exception as e:
            logger.error(f"❌ WebSocket 连接失败: {e}")
            return False
    
    async def disconnect(self):
        """断开连接"""
        self._running = False
        if self.ws:
            await self.ws.close()
            self.ws = None
    
    async def send(self, data: dict):
        """发送消息"""
        if self.ws:
            await self.ws.send(json.dumps(data))
    
    async def recv(self) -> dict:
        """接收消息"""
        if self.ws:
            data = await self.ws.recv()
            return json.loads(data)
        return {}
    
    async def subscribe(self, channel: str, markets: list[str] = None):
        """订阅频道"""
        await self.send({
            "type": "subscribe",
            "channel": channel,
            "markets": markets or []
        })
        logger.info(f"📡 已订阅: {channel}")
    
    async def unsubscribe(self, channel: str):
        """取消订阅"""
        await self.send({
            "type": "unsubscribe", 
            "channel": channel
        })

# =============================================================================
# 订单簿管理器
# =============================================================================

class OrderBookManager:
    """订单簿管理器"""
    
    def __init__(self):
        self.orderbooks: Dict[str, OrderBook] = {}  # token_id -> OrderBook
        self._lock = asyncio.Lock()
    
    async def update_book(self, token_id: str, market_id: str, bids: list, asks: list):
        """更新订单簿"""
        async with self._lock:
            if token_id not in self.orderbooks:
                self.orderbooks[token_id] = OrderBook(
                    market_id=market_id,
                    token_id=token_id
                )
            
            book = self.orderbooks[token_id]
            book.bids = [Order(price=float(b["price"]), size=float(b["size"])) for b in bids[:MAX_ORDERBOOK_DEPTH]]
            book.asks = [Order(price=float(a["price"]), size=float(a["size"])) for a in asks[:MAX_ORDERBOOK_DEPTH]]
            book.last_update = datetime.now()
    
    def get_orderbook(self, token_id: str) -> Optional[OrderBook]:
        """获取订单簿"""
        return self.orderbooks.get(token_id)
    
    def get_all_orderbooks(self) -> Dict[str, OrderBook]:
        """获取所有订单簿"""
        return self.orderbooks.copy()
    
    async def clear(self):
        """清空订单簿"""
        async with self._lock:
            self.orderbooks.clear()

# =============================================================================
# 市场监听器
# =============================================================================

class MarketListener:
    """市场数据监听器"""
    
    def __init__(self, on_arbitrage_callback=None):
        self.ws_client = WSClient()
        self.orderbook_manager = OrderBookManager()
        self.on_arbitrage = on_arbitrage_callback
        self._running = False
        self._market_tokens: Dict[str, list[str]] = {}  # market_id -> token_ids
    
    async def start(self, markets: list[dict]):
        """启动监听"""
        self._running = True
        
        # 构建市场 -> token 映射
        for market in markets:
            market_id = market.get("id")
            tokens = market.get("clobTokenIds", [])
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            
            if market_id and len(tokens) >= 2:
                self._market_tokens[market_id] = tokens
        
        # 连接 WebSocket
        if not await self.ws_client.connect():
            return
        
        # 订阅市场数据
        await self._subscribe_markets()
        
        # 开始监听循环
        await self._listen_loop()
    
    async def _subscribe_markets(self):
        """订阅市场频道"""
        # 简化: 只订阅 market 频道
        await self.ws_client.send({
            "type": "subscribe",
            "channel": "market"
        })
        
        logger.info("📡 已订阅 market 频道")
    
    async def _listen_loop(self):
        """监听循环"""
        logger.info("🔄 开始监听市场数据...")
        
        while self._running:
            try:
                # 使用 async for 循环接收消息
                async for message in self.ws_client.ws:
                    if not self._running:
                        break
                    
                    try:
                        data = json.loads(message)
                        await self._process_message(data)
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.error(f"处理消息错误: {e}")
                        
            except websockets.exceptions.ConnectionClosedOK:
                logger.info("WebSocket 正常关闭")
                break
            except websockets.exceptions.ConnectionClosedError as e:
                logger.warning(f"⚠️ WebSocket 断开: {e}")
                if self._running:
                    await self._reconnect()
            except Exception as e:
                logger.error(f"❌ 监听错误: {e}")
                if self._running:
                    await self._reconnect()
    
    async def _process_message(self, message: dict):
        """处理消息"""
        msg_type = message.get("event_type", message.get("type", ""))
        
        if msg_type == "book" or msg_type == "orderbook":
            # 订单簿更新
            await self._handle_orderbook(message)
        
        elif msg_type == "price_change":
            # 价格更新
            await self._handle_price_change(message)
        
        elif msg_type == "trade" or msg_type == "last_trade_price":
            # 交易更新
            await self._handle_trade(message)
        
        elif msg_type == "subscribed":
            # 订阅确认
            logger.info(f"📩 订阅确认: {message.get('channel')}")
    
    async def _handle_orderbook(self, message: dict):
        """处理订单簿更新"""
        market_id = message.get("market", message.get("market_id"))
        asset_id = message.get("asset_id")
        
        if not asset_id:
            return
        
        # 获取买卖盘
        bids = message.get("bids", message.get("buys", []))
        asks = message.get("asks", message.get("asks", []))
        
        # 更新订单簿
        await self.orderbook_manager.update_book(asset_id, market_id, bids, asks)
        
        # 检查套利机会
        await self._check_arbitrage(asset_id, market_id)
    
    async def _handle_price_change(self, message: dict):
        """处理价格变化"""
        # 简化处理
        pass
    
    async def _handle_trade(self, message: dict):
        """处理交易"""
        # 简化处理
        pass
    
    async def _check_arbitrage(self, token_id: str, market_id: str):
        """检查套利机会"""
        # 找到配对的市场
        for m_id, tokens in self._market_tokens.items():
            if m_id != market_id:
                continue
            
            if len(tokens) < 2:
                continue
            
            yes_token = tokens[0]
            no_token = tokens[1]
            
            # 获取两个订单簿
            yes_book = self.orderbook_manager.get_orderbook(yes_token)
            no_book = self.orderbook_manager.get_orderbook(no_token)
            
            if not yes_book or not no_book:
                continue
            
            # 检查 YES + NO 是否 = $1
            # 最佳买价 + 最佳买价
            total = yes_book.best_bid + no_book.best_bid
            deviation = abs(total - 1.0)
            
            if deviation > 0.01:  # 1% 阈值
                depth = yes_book.depth(5)
                
                signal = ArbitrageSignal(
                    market_id=market_id,
                    token_id_1=yes_token,
                    token_id_2=no_token,
                    bid_price=yes_book.best_bid,
                    ask_price=no_book.best_bid,
                    spread=1.0 - total,
                    spread_pct=deviation * 100,
                    depth=depth
                )
                
                if self.on_arbitrage:
                    await self.on_arbitrage(signal)
                
                logger.info(f"🎯 套利信号: {market_id[:20]}... 偏差: {deviation*100:.2f}%")
    
    async def _reconnect(self):
        """重连"""
        await self.ws_client.disconnect()
        await asyncio.sleep(RECONNECT_DELAY)
        
        if self._running:
            # 重新构建市场列表
            markets = []
            for market_id, tokens in self._market_tokens.items():
                markets.append({"id": market_id, "clobTokenIds": tokens})
            await self.start(markets)
    
    async def stop(self):
        """停止监听"""
        self._running = False
        await self.ws_client.disconnect()
        logger.info("🛑 市场监听已停止")

# =============================================================================
# 实时套利扫描器
# =============================================================================

class RealTimeArbitrageScanner:
    """实时套利扫描器"""
    
    def __init__(self):
        self.listener: Optional[MarketListener] = None
        self.signals: list[ArbitrageSignal] = []
    
    async def start(self, markets: list[dict]):
        """启动扫描"""
        logger.info("🚀 启动实时套利扫描器...")
        
        self.listener = MarketListener(on_arbitrage_callback=self._on_arbitrage)
        await self.listener.start(markets)
    
    async def _on_arbitrage(self, signal: ArbitrageSignal):
        """收到套利信号"""
        self.signals.append(signal)
        
        # 只保留最近 100 个信号
        if len(self.signals) > 100:
            self.signals = self.signals[-100:]
    
    async def stop(self):
        """停止扫描"""
        if self.listener:
            await self.listener.stop()
    
    def get_recent_signals(self, n: int = 10) -> list[ArbitrageSignal]:
        """获取最近的信号"""
        return self.signals[-n:]
    
    def get_orderbooks(self) -> Dict[str, OrderBook]:
        """获取所有订单簿"""
        if self.listener:
            return self.listener.orderbook_manager.get_all_orderbooks()
        return {}

# =============================================================================
# 主函数
# =============================================================================

async def main():
    import sys
    import aiohttp
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    
    # 获取市场数据
    logger.info("📡 获取市场数据...")
    
    markets = []
    async with aiohttp.ClientSession() as session:
        # 获取 crypto 标签
        resp = await session.get(f"{GAMMA_API}/tags/slug/crypto")
        tag = await resp.json()
        
        resp = await session.get(
            f"{GAMMA_API}/markets",
            params={"tag_id": tag["id"], "closed": "false", "limit": 50}
        )
        data = await resp.json()
        
        for m in data:
            tokens = m.get("clobTokenIds", [])
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            
            if len(tokens) >= 2:
                markets.append({
                    "id": m.get("id"),
                    "question": m.get("question"),
                    "clobTokenIds": tokens
                })
    
    logger.info(f"📊 加载了 {len(markets)} 个市场")
    
    # 启动实时扫描
    scanner = RealTimeArbitrageScanner()
    
    try:
        await scanner.start(markets)
    except KeyboardInterrupt:
        logger.info("\n🛑 停止扫描...")
        await scanner.stop()
    
    # 打印最近的信号
    if scanner.signals:
        print("\n📊 最近套利信号:")
        for s in scanner.get_recent_signals(5):
            print(f"  {s.market_id[:30]}... | 偏差: {s.spread_pct:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
