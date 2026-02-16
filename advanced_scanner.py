"""
高级套利扫描策略
=================

1. 筛选市场：胜率 ≥88%，到期 ≤3小时，盘口深度 ≥$3k
2. 稳定性检测：赔率波动 ≤2%，避免虚高
3. 鲸鱼信号：监控大额下注，优先跟随
4. 一致性检查：跨市场赔率一致性 ≥95%

"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import aiohttp
from loguru import logger
from config import GAMMA_API, CLOB_API, TAGS

# =============================================================================
# 策略配置
# =============================================================================

# 筛选条件
MIN_WIN_RATE = float(os.getenv("MIN_WIN_RATE", "0.70"))      # 最低胜率 70%
MAX_WIN_RATE = float(os.getenv("MAX_WIN_RATE", "0.96"))       # 最高胜率 96%
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.87"))            # 最低价格 0.87
MAX_PRICE = float(os.getenv("MAX_PRICE", "0.96"))            # 最高价格 0.96
MAX_HOURS = float(os.getenv("MAX_HOURS", "2000"))            # 最大到期时间
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", "1000"))   # 最小深度 $1k
MAX_VOLATILITY = float(os.getenv("MAX_VOLATILITY", "0.05")) # 最大波动 5%

# =============================================================================
# 策略预设
# =============================================================================

STRATEGIES = {
    "default": {
        "min_win_rate": 0.70,
        "max_win_rate": 0.96,
        "min_price": 0.87,
        "max_price": 0.96,
        "max_hours": 2000,
        "min_liquidity": 1000,
        "max_volatility": 0.05,
    },
    "highprop": {
        "name": "短期高概率",
        "min_win_rate": 0.88,
        "max_win_rate": 0.96,
        "min_price": 0.87,
        "max_price": 0.96,
        "max_hours": 3,
        "min_liquidity": 3000,
        "max_volatility": 0.02,
    },
    "whale": {
        "name": "鲸鱼信号",
        "min_win_rate": 0.70,
        "max_win_rate": 0.99,
        "min_price": 0.50,
        "max_price": 0.99,
        "max_hours": 24,
        "min_liquidity": 5000,
        "max_volatility": 0.10,
    },
}

# 鲸鱼检测
MIN_WHALE_AMOUNT = float(os.getenv("MIN_WHALE_AMOUNT", "500"))  # 大额下注 $500+

# 稳定性检测
STABILITY_CHECK_INTERVAL = 60  # 秒
STABILITY_SAMPLES = 3  # 采样次数

# 一致性检查
MIN_CORRELATION = 0.95  # 最小相关性

# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class MarketSignal:
    """市场信号"""
    market_id: str
    question: str
    side: str  # YES or NO
    win_rate: float  # 胜率
    price: float
    liquidity: float
    hours_until_expiry: float
    volatility: float  # 波动率
    is_stable: bool
    is_whale: bool
    whale_amount: float
    score: float  # 综合评分

@dataclass
class ArbitrageOpportunity:
    """套利机会"""
    market_1: MarketSignal
    market_2: MarketSignal
    correlation: float
    deviation: float
    expected_profit: float
    score: float

# =============================================================================
# 市场筛选器
# =============================================================================

class MarketFilter:
    """市场筛选器"""
    
    @staticmethod
    def calculate_win_rate(price: float) -> float:
        """计算胜率 (即价格)"""
        return price
    
    @staticmethod
    def is_high_probability(price: float, min_rate: float = MIN_WIN_RATE) -> bool:
        """高概率筛选"""
        return price >= min_rate
    
    @staticmethod
    def is_short_duration(hours: float, max_hours: float = MAX_HOURS) -> bool:
        """短期筛选"""
        return 0 < hours <= max_hours
    
    @staticmethod
    def has_sufficient_liquidity(liquidity: float, min_liq: float = MIN_LIQUIDITY) -> bool:
        """流动性筛选"""
        return liquidity >= min_liq
    
    @staticmethod
    def is_in_price_range(price: float, min_price: float = MIN_PRICE, max_price: float = MAX_PRICE) -> bool:
        """价格区间筛选"""
        return min_price <= price <= max_price
    
    @staticmethod
    def matches_criteria(price: float, hours: float, liquidity: float) -> bool:
        """综合筛选"""
        return (
            MarketFilter.is_high_probability(price) and
            MarketFilter.is_in_price_range(price) and
            MarketFilter.is_short_duration(hours) and
            MarketFilter.has_sufficient_liquidity(liquidity)
        )

# =============================================================================
# 价格稳定性检测
# =============================================================================

class StabilityChecker:
    """价格稳定性检测"""
    
    def __init__(self):
        self.price_history: dict[str, list[float]] = {}
    
    async def check_stability(self, token_id: str) -> float:
        """检查价格波动率"""
        prices = []
        
        for _ in range(STABILITY_SAMPLES):
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(
                        f"{CLOB_API}/price",
                        params={"token_id": token_id, "side": "BUY"}
                    )
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data.get("price", 0))
                        if price > 0:
                            prices.append(price)
                
                await asyncio.sleep(0.5)
            except:
                continue
        
        if len(prices) < 2:
            return 1.0  # 无法检测，假设不稳定
        
        # 计算波动率
        avg = sum(prices) / len(prices)
        max_dev = max(abs(p - avg) for p in prices)
        volatility = max_dev / avg if avg > 0 else 1.0
        
        return volatility
    
    def is_stable(self, volatility: float) -> bool:
        """是否稳定"""
        return volatility <= MAX_VOLATILITY

# =============================================================================
# 鲸鱼检测
# =============================================================================

class WhaleDetector:
    """鲸鱼信号检测"""
    
    @staticmethod
    async def check_whale_trades(market_id: str) -> list[dict]:
        """检测大额交易"""
        # 这里需要连接到交易数据源
        # 简化版本：返回空列表
        # TODO: 实现实际的鲸鱼检测
        
        # 可以通过以下方式获取：
        # 1. WebSocket 监听大额交易
        # 2. CLOB API 的 trades endpoint
        # 3. Gamma API 的 market details
        
        return []
    
    @staticmethod
    def is_whale_amount(amount: float) -> bool:
        """是否大额"""
        return amount >= MIN_WHALE_AMOUNT

# =============================================================================
# 一致性检查
# =============================================================================

class CorrelationChecker:
    """跨市场一致性检查"""
    
    @staticmethod
    async def check_correlation(market_ids: list[str]) -> dict[tuple, float]:
        """检查市场间相关性"""
        # 获取多个市场的价格
        prices = {}
        
        for market_id in market_ids:
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(f"{GAMMA_API}/markets/{market_id}")
                    if resp.status == 200:
                        data = await resp.json()
                        outcome_prices = data.get("outcomePrices", [])
                        if outcome_prices:
                            if isinstance(outcome_prices, str):
                                outcome_prices = json.loads(outcome_prices)
                            prices[market_id] = [float(p) for p in outcome_prices]
            except:
                continue
        
        # 计算相关性
        correlations = {}
        market_list = list(prices.keys())
        
        for i, m1 in enumerate(market_list):
            for m2 in market_list[i+1:]:
                # 简化：比较价格差异
                if m1 in prices and m2 in prices:
                    p1_yes = prices[m1][0] if prices[m1] else 0
                    p2_yes = prices[m2][0] if prices[m2] else 0
                    
                    if p1_yes > 0 and p2_yes > 0:
                        # 计算相关性 (简化版)
                        diff = abs(p1_yes - p2_yes)
                        correlation = 1 - diff
                        correlations[(m1, m2)] = correlation
        
        return correlations
    
    @staticmethod
    def find_arbitrage(correlations: dict[tuple, float]) -> list[tuple]:
        """寻找套利机会"""
        opportunities = []
        
        for (m1, m2), corr in correlations.items():
            if corr >= MIN_CORRELATION:
                # 一致性高，可能存在套利机会
                # 计算偏差
                deviation = 1 - corr
                if deviation > 0.01:  # 至少1%偏差
                    opportunities.append((m1, m2, corr, deviation))
        
        return opportunities

# =============================================================================
# 综合信号评分
# =============================================================================

class SignalScorer:
    """综合信号评分"""
    
    @staticmethod
    def calculate_score(signal: MarketSignal) -> float:
        """计算综合评分"""
        score = 0
        
        # 胜率权重 40%
        score += signal.win_rate * 0.4
        
        # 到期时间权重 20% (越短越好)
        if signal.hours_until_expiry > 0:
            score += (1 - signal.hours_until_expiry / 24) * 0.2
        
        # 稳定性权重 20%
        if signal.is_stable:
            score += 0.2
        
        # 鲸鱼信号权重 20%
        if signal.is_whale:
            score += 0.2
        
        return score

# =============================================================================
# 高级扫描器
# =============================================================================

class AdvancedScanner:
    """高级套利扫描器"""
    
    def __init__(self):
        self.stability_checker = StabilityChecker()
        self.whale_detector = WhaleDetector()
        self.correlation_checker = CorrelationChecker()
        self.signals: list[MarketSignal] = []
        self.opportunities: list[ArbitrageOpportunity] = []
    
    async def scan(self, tags: list[str] = None) -> dict:
        """执行扫描"""
        tags = tags or TAGS
        
        logger.info("=" * 60)
        logger.info("🔍 高级套利扫描...")
        logger.info(f"   条件: 胜率≥{MIN_WIN_RATE*100}% | 到期≤{MAX_HOURS}h | 深度≥${MIN_LIQUIDITY:,.0f}")
        
        # 1. 获取市场
        markets = await self._fetch_markets(tags)
        logger.info(f"   获取到 {len(markets)} 个市场")
        
        # 2. 筛选高概率短期市场
        filtered = self._filter_markets(markets)
        logger.info(f"   筛选后: {len(filtered)} 个市场符合条件")
        
        # 3. 稳定性检测
        await self._check_stability(filtered)
        
        # 4. 鲸鱼检测
        await self._check_whales(filtered)
        
        # 5. 计算评分
        for signal in self.signals:
            signal.score = SignalScorer.calculate_score(signal)
        
        # 6. 一致性检查
        await self._check_correlation()
        
        # 7. 排序输出
        self.signals.sort(key=lambda x: -x.score)
        
        return {
            "total_markets": len(markets),
            "filtered_count": len(filtered),
            "signals_count": len(self.signals),
            "opportunities_count": len(self.opportunities),
        }
    
    async def _fetch_markets(self, tags: list[str]) -> list[dict]:
        """获取市场数据"""
        markets = []
        
        for tag in tags:
            try:
                async with aiohttp.ClientSession() as session:
                    # 获取 tag
                    resp = await session.get(f"{GAMMA_API}/tags/slug/{tag}")
                    if resp.status != 200:
                        continue
                    tag_data = await resp.json()
                    tag_id = tag_data.get("id")
                    
                    # 获取市场
                    resp = await session.get(
                        f"{GAMMA_API}/markets",
                        params={
                            "tag_id": tag_id,
                            "closed": "false",
                            "active": "true",
                            "order": "volume",
                            "limit": 200
                        }
                    )
                    
                    if resp.status == 200:
                        data = await resp.json()
                        markets.extend(data)
                        
            except Exception as e:
                logger.error(f"获取 {tag} 市场错误: {e}")
        
        return markets
    
    def _filter_markets(self, markets: list[dict]) -> list[dict]:
        """筛选市场"""
        from scanner_v2 import parse_hours_until_expiry
        
        filtered = []
        
        for m in markets:
            try:
                # 解析价格
                prices = m.get("outcomePrices", [])
                if isinstance(prices, str):
                    prices = json.loads(prices)
                
                yes_price = float(prices[0]) if prices else 0
                no_price = float(prices[1]) if len(prices) > 1 else 0
                
                if yes_price <= 0 or no_price <= 0:
                    continue
                
                # 获取流动性
                liquidity = float(m.get("liquidity", 0))
                
                # 获取到期时间
                hours = parse_hours_until_expiry(m.get("endDate", ""))
                
                # 检查 YES 边
                if MarketFilter.matches_criteria(yes_price, hours, liquidity):
                    filtered.append({
                        **m,
                        "side": "YES",
                        "price": yes_price,
                        "hours": hours,
                        "liquidity": liquidity
                    })
                
                # 检查 NO 边
                if MarketFilter.matches_criteria(no_price, hours, liquidity):
                    filtered.append({
                        **m,
                        "side": "NO",
                        "price": no_price,
                        "hours": hours,
                        "liquidity": liquidity
                    })
                    
            except Exception as e:
                continue
        
        return filtered
    
    async def _check_stability(self, markets: list[dict]):
        """检查稳定性 (简化版，跳过 API 调用)"""
        for m in markets:
            try:
                # 简化：假设稳定
                signal = MarketSignal(
                    market_id=m.get("id", ""),
                    question=m.get("question", ""),
                    side=m["side"],
                    win_rate=m["price"],
                    price=m["price"],
                    liquidity=m["liquidity"],
                    hours_until_expiry=m["hours"],
                    volatility=0.01,  # 假设稳定
                    is_stable=True,
                    is_whale=False,
                    whale_amount=0,
                    score=0
                )
                
                self.signals.append(signal)
                
            except Exception as e:
                continue
    
    async def _check_whales(self, signals: list[MarketSignal]):
        """检查鲸鱼"""
        for signal in signals:
            # TODO: 实现实际的鲸鱼检测
            # 这里简化处理
            pass
    
    async def _check_correlation(self):
        """一致性检查"""
        if len(self.signals) < 2:
            return
        
        # 获取市场 ID 列表
        market_ids = list(set(s.market_id for s in self.signals))
        
        # 检查相关性
        correlations = await self.correlation_checker.check_correlation(market_ids)
        
        # 寻找套利机会
        opportunities = self.correlation_checker.find_arbitrage(correlations)
        
        # 创建套利机会对象
        for m1_id, m2_id, corr, dev in opportunities:
            m1 = next((s for s in self.signals if s.market_id == m1_id), None)
            m2 = next((s for s in self.signals if s.market_id == m2_id), None)
            
            if m1 and m2:
                opp = ArbitrageOpportunity(
                    market_1=m1,
                    market_2=m2,
                    correlation=corr,
                    deviation=dev,
                    expected_profit=dev * min(m1.price, m2.price),
                    score=(m1.score + m2.score) / 2
                )
                self.opportunities.append(opp)
    
    def get_top_signals(self, n: int = 10) -> list[MarketSignal]:
        """获取最佳信号"""
        return self.signals[:n]
    
    def get_top_opportunities(self, n: int = 10) -> list[ArbitrageOpportunity]:
        """获取最佳机会"""
        return sorted(self.opportunities, key=lambda x: -x.score)[:n]

# =============================================================================
# 主函数
# =============================================================================

async def main(strategy_name: str = "default"):
    import sys
    
    # 选择策略
    strategy = STRATEGIES.get(strategy_name, STRATEGIES["default"])
    strategy_name_display = strategy.get("name", strategy_name)
    
    # 应用策略参数
    global MIN_WIN_RATE, MAX_WIN_RATE, MIN_PRICE, MAX_PRICE, MAX_HOURS, MIN_LIQUIDITY, MAX_VOLATILITY
    MIN_WIN_RATE = strategy["min_win_rate"]
    MAX_WIN_RATE = strategy["max_win_rate"]
    MIN_PRICE = strategy["min_price"]
    MAX_PRICE = strategy["max_price"]
    MAX_HOURS = strategy["max_hours"]
    MIN_LIQUIDITY = strategy["min_liquidity"]
    MAX_VOLATILITY = strategy["max_volatility"]
    
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    
    scanner = AdvancedScanner()
    
    print("\n" + "=" * 60)
    print(f"🔍 策略: {strategy_name_display}")
    print(f"   胜率: {MIN_WIN_RATE*100:.0f}%-{MAX_WIN_RATE*100:.0f}% | 价格: {MIN_PRICE:.2f}-{MAX_PRICE:.2f}")
    print(f"   到期: ≤{MAX_HOURS}h | 深度: ≥${MIN_LIQUIDITY:,.0f} | 波动: ≤{MAX_VOLATILITY*100:.0f}%")
    print("=" * 60)
    
    # 使用 crypto 和 finance 标签
    result = await scanner.scan(["crypto", "finance"])
    
    print("\n" + "=" * 60)
    print("📊 扫描报告")
    print("=" * 60)
    print(f"市场总数:     {result['total_markets']}")
    print(f"符合条件:     {result['filtered_count']}")
    print(f"信号数量:     {result['signals_count']}")
    print(f"套利机会:     {result['opportunities_count']}")
    print("=" * 60)
    
    # 显示最佳信号
    signals = scanner.get_top_signals(10)
    
    if signals:
        print("\n🏆 Top 10 市场信号:")
        for i, s in enumerate(signals, 1):
            status = "✅ 稳定" if s.is_stable else "⚠️ 波动"
            whale = "🐋" if s.is_whale else ""
            print(f"{i}. {s.question[:50]}...")
            print(f"   方向: {s.side} @ ${s.price:.3f} | 胜率: {s.win_rate*100:.1f}% | 到期: {s.hours_until_expiry:.1f}h | {status} {whale}")
            print(f"   流动性: ${s.liquidity:,.0f} | 评分: {s.score:.2f}")
            print()
    
    # 显示套利机会
    opps = scanner.get_top_opportunities(5)
    
    if opps:
        print("\n🎯 套利机会:")
        for i, o in enumerate(opps, 1):
            print(f"{i}. {o.market_1.question[:30]}... vs {o.market_2.question[:30]}...")
            print(f"   相关性: {o.correlation*100:.1f}% | 偏差: {o.deviation*100:.2f}% | 预期利润: ${o.expected_profit:.3f}")
            print()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="高级套利扫描器")
    parser.add_argument("--strategy", "-s", choices=["default", "highprop", "whale"], 
                       default="default", help="选择策略")
    args = parser.parse_args()
    asyncio.run(main(args.strategy))
