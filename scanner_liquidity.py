"""
流动性挖矿扫描器 (Liquidity Mining Scanner)
=========================================

策略: 低风险赚取 Polymarket 流动性奖励
参考: @vonzz6 的流动性挖矿攻略

原理:
1. 找到"不交易期"的市场 (周六开盘 → 周一美股开盘前)
2. 双向挂单 (Buy Yes + Buy No)
3. 挂在中间位置，不抢占最佳档位
4. 等待成交或奖励结算

适合:
- 小资金玩家
- 低风险爱好者
- 新手入门
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import aiohttp

from config import GAMMA_API, CLOB_API


# =============================================================================
# 配置
# =============================================================================

# 目标市场类型
TARGET_CATEGORIES = [
    "US-stock-market",      # 美股市场
    "us-stock-market",
]

# 关键词 (17号收盘价等)
TARGET_KEYWORDS = [
    "17",
    "close",
    "settle",
    "nasdaq",
    "spx",
    "spy",
    "qqq",
]

# 挂单价格范围 (中间位置)
DEFAULT_PRICE_RANGE = (0.40, 0.60)

# 最小流动性
MIN_LIQUIDITY = 100

# 最小成交量 (不交易期应该很小)
MAX_VOLUME = 2000


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class LiquidityMarket:
    """流动性挖矿市场"""
    condition_id: str
    question: str
    slug: str
    end_time: datetime
    category: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    minutes_to_start: int  # 距离开始时间
    is_good_target: bool = False


@dataclass
class LiquiditySignal:
    """流动性挖矿信号"""
    market: LiquidityMarket
    recommended_yes_price: float
    recommended_no_price: float
    reason: str
    estimated_reward: float = 1.0


# =============================================================================
# 市场分析
# =============================================================================

class LiquidityMiner:
    """流动性挖矿扫描器"""
    
    def __init__(
        self,
        price_range: tuple = DEFAULT_PRICE_RANGE,
        max_volume: float = MAX_VOLUME,
    ):
        self.price_range = price_range
        self.max_volume = max_volume
    
    async def scan_markets(self) -> list[LiquidityMarket]:
        """扫描适合流动性挖矿的市场"""
        url = f"{GAMMA_API}/markets"
        
        params = {
            "closed": "false",
            "limit": 200,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                markets_data = await resp.json()
        
        results = []
        now = datetime.now()
        
        for market in markets_data:
            # 解析基本信息
            question = market.get("question", "").lower()
            slug = market.get("slug", "").lower()
            category = market.get("category", "").lower()
            
            # 检查是否为目标市场
            is_target = self._is_target_market(question, slug, category)
            
            # 获取时间
            start_date = market.get("startDate")
            end_date = market.get("endDate")
            
            if not start_date:
                continue
            
            start_time = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            minutes_to_start = int((start_time - now).total_seconds() / 60)
            
            # 只关心即将开始的市场 (不交易期)
            if minutes_to_start < -60:  # 已经开始了超过1小时
                continue
            
            # 获取价格
            outcome_prices = market.get("outcomePrices", "[]")
            try:
                prices = json.loads(outcome_prices)
                yes_price = float(prices[0]) if len(prices) > 0 else 0
                no_price = float(prices[1]) if len(prices) > 1 else 0
            except:
                yes_price = 0
                no_price = 0
            
            volume = float(market.get("volume", 0))
            liquidity = float(market.get("liquidity", 0))
            
            liquidity_market = LiquidityMarket(
                condition_id=market.get("conditionId", ""),
                question=market.get("question", ""),
                slug=market.get("slug", ""),
                end_time=datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else now,
                category=category,
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                liquidity=liquidity,
                minutes_to_start=minutes_to_start,
                is_good_target=is_target,
            )
            
            results.append(liquidity_market)
        
        return results
    
    def _is_target_market(
        self,
        question: str,
        slug: str,
        category: str,
    ) -> bool:
        """判断是否为目标市场"""
        # 检查类别
        for cat in TARGET_CATEGORIES:
            if cat.lower() in category:
                return True
        
        # 检查关键词
        for kw in TARGET_KEYWORDS:
            if kw in question or kw in slug:
                return True
        
        return False
    
    def analyze_opportunities(
        self,
        markets: list[LiquidityMarket],
    ) -> list[LiquiditySignal]:
        """分析流动性挖矿机会"""
        signals = []
        
        for market in markets:
            # 过滤条件
            if market.volume > self.max_volume:
                continue  # 成交量太大，竞争激烈
            
            if market.liquidity < MIN_LIQUIDITY:
                continue  # 流动性太低
            
            # 检查价格是否在合适范围
            yes_in_range = self.price_range[0] <= market.yes_price <= self.price_range[1]
            no_in_range = self.price_range[0] <= market.no_price <= self.price_range[1]
            
            if not (yes_in_range or no_in_range):
                continue  # 价格不在推荐范围
            
            # 推荐挂单价格 (中间位置)
            mid_price = 0.5
            recommended_yes = mid_price
            recommended_no = mid_price
            
            # 分析理由
            reasons = []
            
            if market.is_good_target:
                reasons.append("目标市场 (美股相关)")
            
            if market.volume < 500:
                reasons.append("超低成交量 (竞争小)")
            
            if market.minutes_to_start > 0:
                reasons.append(f"还有 {market.minutes_to_start} 分钟开始")
            else:
                reasons.append("不交易期")
            
            if market.yes_price > 0.4 and market.yes_price < 0.6:
                reasons.append("价格适中")
            
            signal = LiquiditySignal(
                market=market,
                recommended_yes_price=recommended_yes,
                recommended_no_price=recommended_no,
                reason=" | ".join(reasons),
            )
            signals.append(signal)
        
        # 排序：优先目标市场，然后低成交量
        signals.sort(key=lambda x: (
            not x.market.is_good_target,
            x.market.volume,
        ))
        
        return signals
    
    async def print_opportunities(self):
        """打印机会列表"""
        print("\n" + "="*60)
        print("🔍 流动性挖矿扫描器")
        print("="*60)
        
        markets = await self.scan_markets()
        print(f"找到 {len(markets)} 个市场")
        
        signals = self.analyze_opportunities(markets)
        
        if signals:
            print(f"\n🎯 发现 {len(signals)} 个优质机会:\n")
            
            for i, s in enumerate(signals[:10], 1):
                m = s.market
                print(f"{i}. {m.question[:50]}...")
                print(f"   💰 Yes: {m.yes_price:.2f} | No: {m.no_price:.2f}")
                print(f"   📊 成交量: ${m.volume:.0f} | 流动性: ${m.liquidity:.0f}")
                print(f"   ⏰ {'还有 ' + str(m.minutes_to_start) + ' 分钟开始' if m.minutes_to_start > 0 else '不交易期'}")
                print(f"   📝 {s.reason}")
                print(f"   🎯 推荐挂单: Yes @ {s.recommended_yes_price:.2f} | No @ {s.recommended_no_price:.2f}")
                print()
        else:
            print("\n❌ 暂无可用机会")
            print("提示: 周末和美股休市时机会更多")


# =============================================================================
# 主函数
# =============================================================================

async def main():
    miner = LiquidityMiner()
    await miner.print_opportunities()


if __name__ == "__main__":
    asyncio.run(main())
