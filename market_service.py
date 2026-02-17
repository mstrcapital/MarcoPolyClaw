"""
市场服务 (Market Service)
=====================

功能:
- 市场查询
- K线数据
- 订单簿分析
- 套利检测
- 搜索热门市场
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Optional
import aiohttp

from config import GAMMA_API, CLOB_API


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class MarketToken:
    """市场代币"""
    token_id: str
    outcome: str
    price: float


@dataclass
class Market:
    """市场信息"""
    condition_id: str
    question: str
    slug: str
    description: str
    tokens: list[MarketToken]
    active: bool
    closed: bool
    end_date: str
    volume: float
    liquidity: float


@dataclass
class OrderbookLevel:
    """订单簿档位"""
    price: float
    size: float


@dataclass
class Orderbook:
    """订单簿"""
    token_id: str
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]
    timestamp: int


@dataclass
class ProcessedOrderbook:
    """处理后的订单簿（带套利分析）"""
    yes_token_id: str
    no_token_id: str
    yes_bid: float       # YES 当前买一
    yes_ask: float       # YES 当前卖一
    no_bid: float        # NO 当前买一
    no_ask: float        # NO 当前卖一
    
    # 套利分析
    long_arb_profit: float   # Long arb 利润 (买入 YES + 买入 NO)
    short_arb_profit: float  # Short arb 利润
    
    # 有效价格 (考虑镜像订单)
    effective_yes_price: float
    effective_no_price: float


@dataclass
class KLine:
    """K线数据"""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class ArbitrageOpportunity:
    """套利机会"""
    type: str           # "long" 或 "short"
    profit: float       # 利润比例
    yes_price: float
    no_price: float
    action: str         # 操作建议


@dataclass
class PricePoint:
    """价格点"""
    timestamp: int
    price: float


# =============================================================================
# 市场服务
# =============================================================================

class MarketService:
    """市场数据服务"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    # =========================================================================
    # 市场查询
    # =========================================================================
    
    async def get_market(self, identifier: str) -> Optional[Market]:
        """
        通过 slug 或 condition_id 获取市场
        
        Args:
            identifier: slug 或 condition_id
        
        Returns:
            Market 或 None
        """
        session = await self._get_session()
        
        # 先尝试通过 CLOB API
        url = f"{CLOB_API}/markets"
        params = {"condition_id": identifier} if identifier.startswith("0x") else {"slug": identifier}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    return self._parse_market(data[0])
        
        return None
    
    async def get_market_by_condition_id(self, condition_id: str) -> Optional[Market]:
        """通过 condition_id 获取市场"""
        session = await self._get_session()
        
        url = f"{CLOB_API}/markets"
        params = {"condition_id": condition_id}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    return self._parse_market(data[0])
        
        return None
    
    async def get_markets(self, limit: int = 50, cursor: str = None) -> tuple[list[Market], str]:
        """获取市场列表"""
        session = await self._get_session()
        
        url = f"{CLOB_API}/markets"
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                markets = [self._parse_market(m) for m in data.get("data", [])]
                next_cursor = data.get("next_cursor", "")
                return markets, next_cursor
        
        return [], ""
    
    def _parse_market(self, data: dict) -> Market:
        """解析市场数据"""
        tokens = []
        for t in data.get("tokens", []):
            tokens.append(MarketToken(
                token_id=t.get("token_id", ""),
                outcome=t.get("outcome", ""),
                price=float(t.get("price", 0)),
            ))
        
        return Market(
            condition_id=data.get("condition_id", ""),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            description=data.get("description", ""),
            tokens=tokens,
            active=data.get("active", True),
            closed=data.get("closed", False),
            end_date=data.get("endDate", ""),
            volume=float(data.get("volume", 0)),
            liquidity=float(data.get("liquidity", 0)),
        )
    
    # =========================================================================
    # Gamma API (市场发现)
    # =========================================================================
    
    async def search_markets(self, query: str, limit: int = 20) -> list[dict]:
        """搜索市场"""
        session = await self._get_session()
        
        url = f"{GAMMA_API}/markets"
        params = {"q": query, "limit": limit}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
        
        return []
    
    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """获取热门市场"""
        session = await self._get_session()
        
        url = f"{GAMMA_API}/markets"
        params = {"limit": limit, "closed": "false"}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                # 按成交量排序
                sorted_markets = sorted(data, key=lambda x: float(x.get("volume", 0)), reverse=True)
                return [self._parse_market(m) for m in sorted_markets[:limit]]
        
        return []
    
    async def get_markets_by_tag(self, tag: str, limit: int = 20) -> list[Market]:
        """通过标签获取市场"""
        session = await self._get_session()
        
        url = f"{GAMMA_API}/markets"
        params = {"tag": tag, "limit": limit, "closed": "false"}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [self._parse_market(m) for m in data]
        
        return []
    
    # =========================================================================
    # 订单簿
    # =========================================================================
    
    async def get_orderbook(self, token_id: str) -> Orderbook:
        """获取订单簿"""
        session = await self._get_session()
        
        url = f"{CLOB_API}/orderbook"
        params = {"token_id": token_id}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return self._parse_orderbook(token_id, data)
        
        return Orderbook(token_id=token_id, bids=[], asks=[], timestamp=0)
    
    def _parse_orderbook(self, token_id: str, data: dict) -> Orderbook:
        """解析订单簿"""
        bids = [
            OrderbookLevel(price=float(b[0]), size=float(b[1]))
            for b in data.get("bids", [])
        ]
        asks = [
            OrderbookLevel(price=float(a[0]), size=float(a[1]))
            for a in data.get("asks", [])
        ]
        
        return Orderbook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=int(data.get("timestamp", 0)),
        )
    
    async def get_processed_orderbook(
        self,
        yes_token_id: str,
        no_token_id: str,
    ) -> ProcessedOrderbook:
        """
        获取处理后的订单簿（带套利分析）
        
        注意: Polymarket 订单簿是镜像的:
        - Buy YES @ P = Sell NO @ (1-P)
        - 所以同一订单会在两个订单簿中出现
        """
        # 获取两个订单簿
        yes_book, no_book = await asyncio.gather(
            self.get_orderbook(yes_token_id),
            self.get_orderbook(no_token_id),
        )
        
        # 取最佳价格
        yes_bid = yes_book.bids[0].price if yes_book.bids else 0
        yes_ask = yes_book.asks[0].price if yes_book.asks else 1
        no_bid = no_book.bids[0].price if no_book.bids else 0
        no_ask = no_book.asks[0].price if no_book.asks else 1
        
        # 计算套利
        # Long arb: 买入 YES + 买入 NO -> 成本 = ask_yes + ask_no
        long_cost = yes_ask + no_ask
        long_arb_profit = max(0, 1 - long_cost)
        
        # Short arb: 卖空 YES + 卖空 NO -> 收益 = bid_yes + bid_no
        short_revenue = yes_bid + no_bid
        short_arb_profit = max(0, short_revenue - 1)
        
        # 有效价格 (考虑镜像订单)
        effective_yes = min(yes_ask, 1 - no_bid)
        effective_no = min(no_ask, 1 - yes_bid)
        
        return ProcessedOrderbook(
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            long_arb_profit=long_arb_profit,
            short_arb_profit=short_arb_profit,
            effective_yes_price=effective_yes,
            effective_no_price=effective_no,
        )
    
    # =========================================================================
    # 套利检测
    # =========================================================================
    
    async def detect_arbitrage(
        self,
        yes_token_id: str,
        no_token_id: str,
        min_profit: float = 0.005,  # 最小利润 0.5%
    ) -> Optional[ArbitrageOpportunity]:
        """
        检测套利机会
        
        Args:
            yes_token_id: YES token ID
            no_token_id: NO token ID
            min_profit: 最小利润阈值
        
        Returns:
            ArbitrageOpportunity 或 None
        """
        book = await self.get_processed_orderbook(yes_token_id, no_token_id)
        
        # Long arb
        if book.long_arb_profit >= min_profit:
            return ArbitrageOpportunity(
                type="long",
                profit=book.long_arb_profit,
                yes_price=book.yes_ask,
                no_price=book.no_ask,
                action=f"Buy YES @ {book.yes_ask:.4f} + Buy NO @ {book.no_ask:.4f} = {book.yes_ask + book.no_ask:.4f} -> Profit: {book.long_arb_profit*100:.2f}%",
            )
        
        # Short arb
        if book.short_arb_profit >= min_profit:
            return ArbitrageOpportunity(
                type="short",
                profit=book.short_arb_profit,
                yes_price=book.yes_bid,
                no_price=book.no_bid,
                action=f"Sell YES @ {book.yes_bid:.4f} + Sell NO @ {book.no_bid:.4f} = {book.yes_bid + book.no_bid:.4f} -> Profit: {book.short_arb_profit*100:.2f}%",
            )
        
        return None
    
    # =========================================================================
    # K线数据
    # =========================================================================
    
    async def get_prices_history(
        self,
        token_id: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> list[PricePoint]:
        """
        获取历史价格
        
        Args:
            token_id: Token ID
            interval: 1h, 6h, 1d, 1w, max
            limit: 数量
        """
        session = await self._get_session()
        
        url = f"{CLOB_API}/prices-history"
        params = {
            "market": token_id,
            "interval": interval,
            "limit": limit,
        }
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                history = data.get("history", [])
                return [
                    PricePoint(timestamp=p.get("t", 0), price=p.get("p", 0))
                    for p in history
                ]
        
        return []
    
    async def get_klines(
        self,
        token_id: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> list[KLine]:
        """
        获取 K线数据 (从成交数据聚合)
        
        Args:
            token_id: Token ID
            interval: 1m, 5m, 15m, 30m, 1h, 4h, 1d
            limit: 数量
        """
        session = await self._get_session()
        
        url = f"{CLOB_API}/trades"
        params = {
            "token_id": token_id,
            "limit": limit,
        }
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                trades = data.get("trades", [])
                
                # 简单聚合为 K线
                # 实际实现需要更复杂的聚合逻辑
                return [
                    KLine(
                        timestamp=int(t.get("timestamp", 0)),
                        open=float(t.get("price", 0)),
                        high=float(t.get("price", 0)),
                        low=float(t.get("price", 0)),
                        close=float(t.get("price", 0)),
                        volume=float(t.get("size", 0)),
                    )
                    for t in trades
                ]
        
        return []


# =============================================================================
# 快速函数
# =============================================================================

async def get_market_service() -> MarketService:
    """获取 MarketService 实例"""
    return MarketService()


# =============================================================================
# 示例
# =============================================================================

async def main():
    service = await get_market_service()
    
    print("Market Service")
    print("=" * 40)
    
    # 获取热门市场
    trending = await service.get_trending_markets(5)
    print(f"Trending markets: {len(trending)}")
    
    for m in trending[:3]:
        print(f"  {m.question[:50]}...")
        print(f"    Volume: ${m.volume:,.0f}")
    
    await service.close()


if __name__ == "__main__":
    asyncio.run(main())
