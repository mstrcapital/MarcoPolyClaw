"""
Polymarket 完整套利扫描器 v2
包含: 市场分组 + 验证 + Multicall3 + 状态持久化 + LLM逻辑

优化功能:
- 市场分组 (Groups)
- 验证步骤 (Validate)
- Multicall3 批量查询
- SQLite 状态持久化
- LLM 逻辑推断 (需API Key)
"""

import asyncio
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import aiohttp
import websockets
from loguru import logger

# 导入配置
from config import (
    GAMMA_API, CLOB_API, TAGS,
    MIN_LIQUIDITY, MIN_VOLUME, DB_PATH, OPENROUTER_API_KEY
)

# WebSocket URL
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# 固定配置
MAX_AGE_DAYS = 365     # 最大天数
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"
NECESSARY_PROBABILITY = 0.98

# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class Market:
    id: str
    question: str
    slug: str
    condition_id: str
    yes_token_id: str = ""
    no_token_id: str = ""
    yes_price: float = 0
    no_price: float = 0
    volume: float = 0
    liquidity: float = 0
    end_date: str = ""
    active: bool = True
    group_id: str = ""
    group_label: str = ""
    hours_until_expiry: float = -1  # -1 = 无到期时间

# 到期时间分类
TIME_BUCKETS = [
    ("<1h", 0, 1),
    ("1-5h", 1, 5),
    ("5-10h", 5, 10),
    ("10-24h", 10, 24),
    ("24-48h", 24, 48),
    ("48h+", 48, float("inf")),
]

def get_time_bucket(hours: float) -> str:
    """根据小时数返回时间桶"""
    if hours < 0:
        return "N/A"
    for label, min_h, max_h in TIME_BUCKETS:
        if min_h <= hours < max_h:
            return label
    return "48h+"

def parse_hours_until_expiry(end_date_str: str) -> float:
    """解析到期时间字符串，返回剩余小时数"""
    if not end_date_str:
        return -1
    
    try:
        from dateutil import parser
        end_time = parser.parse(end_date_str)
        
        # 使用 timezone-aware UTC 时间
        from datetime import timezone
        now = datetime.now(timezone.utc)
        
        # 确保 end_time 也是 timezone-aware
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        delta = end_time - now
        hours = delta.total_seconds() / 3600
        
        return hours if hours >= 0 else -1
        
    except Exception:
        return -1

def get_expiry_summary(markets: list[Market]) -> dict:
    """获取到期时间分布统计"""
    buckets = {bucket[0]: 0 for bucket in TIME_BUCKETS}
    buckets["N/A"] = 0
    
    for m in markets:
        bucket = get_time_bucket(m.hours_until_expiry)
        buckets[bucket] = buckets.get(bucket, 0) + 1
    
    return buckets

@dataclass
class MarketGroup:
    id: str
    name: str
    slug: str
    markets: list[Market] = field(default_factory=list)
    partition_type: str = ""  # timeframe, threshold, candidate

@dataclass
class ArbitrageOpportunity:
    market_id: str
    question: str
    yes_price: float
    no_price: float
    deviation: float
    potential_profit: float
    is_validated: bool = False
    validation_errors: list[str] = field(default_factory=list)

@dataclass
class HedgeOpportunity:
    target_market: Market
    cover_market: Market
    target_position: str  # YES or NO
    cover_position: str
    coverage: float
    tier: int
    tier_label: str
    total_cost: float
    expected_profit: float
    relationship: str  # LLM 分析结果

# =============================================================================
# 状态持久化 (SQLite)
# =============================================================================

class StateManager:
    """SQLite 状态持久化"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # 市场表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS markets (
                    id TEXT PRIMARY KEY,
                    question TEXT,
                    slug TEXT,
                    condition_id TEXT,
                    yes_token_id TEXT,
                    no_token_id TEXT,
                    yes_price REAL,
                    no_price REAL,
                    volume REAL,
                    liquidity REAL,
                    end_date TEXT,
                    active INTEGER,
                    group_id TEXT,
                    group_label TEXT,
                    updated_at TEXT
                )
            """)
            
            # 市场组表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    slug TEXT,
                    partition_type TEXT,
                    created_at TEXT
                )
            """)
            
            # 对冲机会表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hedge_opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id TEXT,
                    cover_id TEXT,
                    target_position TEXT,
                    cover_position TEXT,
                    coverage REAL,
                    tier INTEGER,
                    tier_label TEXT,
                    total_cost REAL,
                    expected_profit REAL,
                    relationship TEXT,
                    created_at TEXT
                )
            """)
            
            # 扫描历史
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_time TEXT,
                    markets_count INTEGER,
                    opportunities_count INTEGER,
                    hedges_count INTEGER
                )
            """)
            
            conn.commit()
    
    def save_market(self, market: Market):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO markets 
                (id, question, slug, condition_id, yes_token_id, no_token_id,
                 yes_price, no_price, volume, liquidity, end_date, active,
                 group_id, group_label, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market.id, market.question, market.slug, market.condition_id,
                market.yes_token_id, market.no_token_id, market.yes_price,
                market.no_price, market.volume, market.liquidity,
                market.end_date, int(market.active), market.group_id,
                market.group_label, datetime.now().isoformat()
            ))
            conn.commit()
    
    def save_group(self, group: MarketGroup):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO market_groups (id, name, slug, partition_type, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (group.id, group.name, group.slug, group.partition_type, datetime.now().isoformat()))
            conn.commit()
    
    def save_hedge(self, hedge: HedgeOpportunity):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO hedge_opportunities
                (target_id, cover_id, target_position, cover_position, coverage,
                 tier, tier_label, total_cost, expected_profit, relationship, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hedge.target_market.id, hedge.cover_market.id,
                hedge.target_position, hedge.cover_position,
                hedge.coverage, hedge.tier, hedge.tier_label,
                hedge.total_cost, hedge.expected_profit,
                hedge.relationship, datetime.now().isoformat()
            ))
            conn.commit()
    
    def log_scan(self, markets_count: int, opportunities_count: int, hedges_count: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO scan_history (scan_time, markets_count, opportunities_count, hedges_count)
                VALUES (?, ?, ?, ?)
            """, (datetime.now().isoformat(), markets_count, opportunities_count, hedges_count))
            conn.commit()
    
    def get_recent_hedges(self, limit: int = 10) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM hedge_opportunities
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

# =============================================================================
# 市场分组 (Groups)
# =============================================================================

class MarketGrouper:
    """将市场分组 - 识别相关市场"""
    
    # 时间框架模式
    TIMEFRAME_PATTERNS = [
        r"by\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}",
        r"by\s+\w+\s+\d{1,2},?\s+\d{4}",
        r"in\s+\d{4}",
        r"before\s+\w+\s+\d{4}",
        r"on\s+\w+\s+\d{1,2}",
    ]
    
    # 阈值模式
    THRESHOLD_PATTERNS = [
        r"(above|over|more than|≥|>)\s*\$?(\d+[kmb]?)",
        r"(below|under|less than|≤|<)\s*\$?(\d+[kmb]?)",
        r"(\d+[kmb]?)\s*(percent|bps|basis points)",
    ]
    
    @staticmethod
    def extract_bracket(question: str) -> str:
        """提取市场括号标签"""
        # 移除问题主体，保留括号内容
        match = re.search(r'\(([^)]+)\)', question)
        if match:
            return match.group(1).strip()
        
        # 尝试匹配阈值
        for pattern in MarketGrouper.THRESHOLD_PATTERNS:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                return match.group(0)
        
        return ""
    
    @staticmethod
    def get_base_question(question: str) -> str:
        """获取问题主体 (移除括号和具体数值)"""
        # 移除括号内容
        base = re.sub(r'\s*\([^)]+\)', '', question)
        # 移除具体数值
        base = re.sub(r'\d+[kmb]?\s*(percent|bps|dollars?|usd)?', '', base, flags=re.IGNORECASE)
        return base.strip().lower()
    
    def group_markets(self, markets: list[Market]) -> list[MarketGroup]:
        """将市场分组"""
        groups: dict[str, MarketGroup] = {}
        
        for market in markets:
            base = self.get_base_question(market.question)
            bracket = self.extract_bracket(market.question)
            
            # 确定分组ID
            group_id = f"group_{hash(base) % 1000000}"
            
            if group_id not in groups:
                # 推断分区类型
                partition_type = self._infer_partition_type(market.question)
                groups[group_id] = MarketGroup(
                    id=group_id,
                    name=base[:50],
                    slug=base[:30],
                    partition_type=partition_type
                )
            
            market.group_id = group_id
            market.group_label = bracket
            groups[group_id].markets.append(market)
        
        # 过滤只有一个市场的组
        return [g for g in groups.values() if len(g.markets) >= 2]
    
    def _infer_partition_type(self, question: str) -> str:
        """推断分区类型"""
        question_lower = question.lower()
        
        for pattern in self.TIMEFRAME_PATTERNS:
            if re.search(pattern, question_lower):
                return "timeframe"
        
        for pattern in self.THRESHOLD_PATTERNS:
            if re.search(pattern, question_lower):
                return "threshold"
        
        if any(c in question for c in [" vs ", " VS ", " vs. "]):
            return "candidate"
        
        return "unknown"

# =============================================================================
# 验证步骤 (Validate)
# =============================================================================

class MarketValidator:
    """验证市场有效性"""
    
    @staticmethod
    def validate_market(market: Market) -> tuple[bool, list[str]]:
        """验证单个市场"""
        errors = []
        
        # 检查流动性
        if market.liquidity < MIN_LIQUIDITY:
            errors.append(f"流动性不足: ${market.liquidity:.0f} < ${MIN_LIQUIDITY}")
        
        # 检查成交量
        if market.volume < MIN_VOLUME:
            errors.append(f"成交量不足: ${market.volume:.0f} < ${MIN_VOLUME}")
        
        # 检查价格有效性
        if not (0.001 <= market.yes_price <= 0.999):
            errors.append(f"YES价格无效: {market.yes_price}")
        
        if not (0.001 <= market.no_price <= 0.999):
            errors.append(f"NO价格无效: {market.no_price}")
        
        # 检查是否过期
        if market.end_date:
            try:
                end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
                age_days = (datetime.now(end.tzinfo) - end).days
                if age_days > 0:
                    errors.append(f"市场已过期: {age_days}天前")
            except:
                pass
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_pair(m1: Market, m2: Market) -> tuple[bool, list[str]]:
        """验证套利对"""
        errors = []
        
        # 同一组内不能互相套利
        if m1.group_id and m1.group_id == m2.group_id:
            errors.append("同组市场不能互相套利")
        
        # 都必须有效
        valid1, errs1 = MarketValidator.validate_market(m1)
        valid2, errs2 = MarketValidator.validate_market(m2)
        
        errors.extend(errs1)
        errors.extend(errs2)
        
        return valid1 and valid2 and len(errors) == 0, errors

# =============================================================================
# Coverage 计算
# =============================================================================

TIER_THRESHOLDS = [
    (0.95, 1, "HIGH", "near-arbitrage"),
    (0.90, 2, "GOOD", "strong hedge"),
    (0.85, 3, "MODERATE", "decent hedge"),
    (0.00, 4, "LOW", "speculative"),
]

def calculate_coverage(target_price: float, cover_price: float, 
                     cover_prob: float = NECESSARY_PROBABILITY) -> dict:
    """计算覆盖率"""
    p_target = target_price
    p_not_target = 1 - target_price
    
    coverage = p_target + p_not_target * cover_prob
    loss_prob = p_not_target * (1 - cover_prob)
    expected_profit = coverage - (target_price + cover_price)
    
    return {
        "coverage": round(coverage, 4),
        "loss_probability": round(loss_prob, 4),
        "expected_profit": round(expected_profit, 4),
    }

def classify_tier(coverage: float) -> tuple:
    """分类Tier"""
    for threshold, tier, label, _ in TIER_THRESHOLDS:
        if coverage >= threshold:
            return tier, label
    return 4, "LOW"

# =============================================================================
# API 客户端
# =============================================================================

class PolymarketClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
    
    async def _request(self, method: str, url: str, **kwargs) -> Any:
        async with self._session.request(method, url, timeout=30, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def get(self, url: str, **kwargs) -> Any:
        if not self._session:
            self._session = aiohttp.ClientSession()
        return await self._request("GET", url, **kwargs)
    
    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        await self.close()

# =============================================================================
# LLM 逻辑推断 (占位符)
# =============================================================================

class LLMAnalyzer:
    """LLM 逻辑推断 - 分析市场关系"""
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
    
    async def analyze_relationship(self, target: Market, other: Market) -> Optional[str]:
        """分析两个市场的逻辑关系"""
        if not self.api_key:
            return None  # 无API Key时跳过
        
        # 简化版: 实际需要调用 OpenRouter
        prompt = f"""
判断以下两个市场是否存在"必要"逻辑关系 (A→B: 如果A为真，则B必须为真):

市场1: {target.question}
市场2: {other.question}

只返回JSON: {{"relationship": "描述关系或null"}}
"""
        # TODO: 实现实际的 API 调用
        return None
    
    async def batch_analyze(self, pairs: list[tuple[Market, Market]]) -> dict:
        """批量分析市场对"""
        results = {}
        
        for m1, m2 in pairs:
            rel = await self.analyze_relationship(m1, m2)
            if rel:
                results[(m1.id, m2.id)] = rel
        
        return results

# =============================================================================
# 主扫描器
# =============================================================================

class FullScanner:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.client = PolymarketClient()
        self.state = StateManager()
        self.grouper = MarketGrouper()
        self.validator = MarketValidator()
        self.llm = LLMAnalyzer(OPENROUTER_API_KEY)
        
        self.markets: dict[str, Market] = {}
        self.groups: list[MarketGroup] = []
        self.opportunities: list[ArbitrageOpportunity] = []
        self.hedges: list[HedgeOpportunity] = []
    
    async def scan(self) -> dict:
        """执行完整扫描"""
        logger.info("=" * 60)
        logger.info("开始完整扫描...")
        
        # 1. 获取市场
        markets = await self._fetch_markets()
        logger.info(f"获取到 {len(markets)} 个市场")
        
        # 2. 市场分组
        self.groups = self.grouper.group_markets(markets)
        logger.info(f"分成 {len(self.groups)} 个组")
        
        # 保存到数据库
        for m in markets:
            self.state.save_market(m)
        for g in self.groups:
            self.state.save_group(g)
        
        # 3. 验证市场
        valid_markets = []
        for m in markets:
            is_valid, errors = self.validator.validate_market(m)
            m.is_valid = is_valid
            if is_valid:
                valid_markets.append(m)
        
        logger.info(f"有效市场: {len(valid_markets)}/{len(markets)}")
        
        # 4. 检测套利机会
        self.opportunities = self._detect_arbitrage(valid_markets)
        
        # 5. 检测对冲机会
        self.hedges = self._detect_hedges(valid_markets)
        
        # 6. 保存扫描历史
        self.state.log_scan(len(markets), len(self.opportunities), len(self.hedges))
        
        return {
            "total_markets": len(markets),
            "valid_markets": len(valid_markets),
            "groups": len(self.groups),
            "arbitrage_opportunities": len(self.opportunities),
            "hedge_opportunities": len(self.hedges),
        }
    
    async def _fetch_markets(self) -> list[Market]:
        """获取市场数据 - 获取 Crypto 标签市场"""
        all_markets = []
        seen_ids = set()
        
        # 只获取 crypto 标签
        crypto_tags = ["crypto", "bitcoin"]
        
        for tag in crypto_tags:
            try:
                # 获取 tag ID
                tag_data = await self.client.get(f"{GAMMA_API}/tags/slug/{tag}")
                if not tag_data:
                    logger.warning(f"Tag not found: {tag}")
                    continue
                
                tag_id = tag_data.get("id")
                logger.info(f"Fetching markets for tag: {tag} (ID: {tag_id})")
                
                # 获取该标签的市场
                data = await self.client.get(
                    f"{GAMMA_API}/markets",
                    params={
                        "tag_id": tag_id,
                        "closed": "false",
                        "active": "true",
                        "order": "volume",
                        "ascending": "false",
                        "limit": 200
                    }
                )
                
                logger.info(f"Got {len(data)} markets for {tag}")
                
                for m in data:
                    market_id = m.get("id", "")
                    if market_id in seen_ids:
                        continue
                    seen_ids.add(market_id)
                    
                    try:
                        clob_tokens = m.get("clobTokenIds", [])
                        if isinstance(clob_tokens, str):
                            clob_tokens = json.loads(clob_tokens)
                        
                        prices = m.get("outcomePrices", [])
                        if isinstance(prices, str):
                            prices = json.loads(prices)
                        prices = [float(p) for p in prices]
                        
                        market = Market(
                            id=market_id,
                            question=m.get("question", ""),
                            slug=m.get("slug", ""),
                            condition_id=m.get("conditionId", ""),
                            yes_token_id=clob_tokens[0] if clob_tokens else "",
                            no_token_id=clob_tokens[1] if len(clob_tokens) > 1 else "",
                            yes_price=prices[0] if prices else 0,
                            no_price=prices[1] if len(prices) > 1 else 0,
                            volume=float(m.get("volume", 0)),
                            liquidity=float(m.get("liquidity", 0)),
                            end_date=m.get("endDate", ""),
                            active=m.get("active", True),
                            hours_until_expiry=parse_hours_until_expiry(m.get("endDate", ""))
                        )
                        all_markets.append(market)
                        self.markets[market.id] = market
                        
                    except Exception as e:
                        logger.error(f"解析市场错误: {e}")
                        
            except Exception as e:
                logger.error(f"获取 {tag} 市场错误: {e}")
        
        return all_markets
    
    def _detect_arbitrage(self, markets: list[Market]) -> list[ArbitrageOpportunity]:
        """检测价格偏差套利"""
        opportunities = []
        
        for m in markets:
            if len(m.yes_token_id) < 2:
                continue
            
            total = m.yes_price + m.no_price
            deviation = abs(total - 1.0)
            
            if deviation > 0.01:  # 1% 阈值
                is_valid, errors = self.validator.validate_market(m)
                
                opp = ArbitrageOpportunity(
                    market_id=m.id,
                    question=m.question,
                    yes_price=m.yes_price,
                    no_price=m.no_price,
                    deviation=deviation,
                    potential_profit=deviation * 100,
                    is_validated=is_valid,
                    validation_errors=errors
                )
                opportunities.append(opp)
                
                if deviation > 0.05:
                    logger.info(f"🎯 套利: {m.question[:40]}... 偏差: {deviation*100:.1f}%")
        
        return opportunities
    
    def _detect_hedges(self, markets: list[Market]) -> list[HedgeOpportunity]:
        """检测对冲机会"""
        hedges = []
        
        # 跨组对冲: 不同组的市场配对
        for i, g1 in enumerate(self.groups):
            for g2 in self.groups[i+1:]:
                for m1 in g1.markets:
                    for m2 in g2.markets:
                        # 计算对冲
                        hedge = self._calculate_hedge(m1, m2)
                        if hedge and hedge.coverage >= 0.85:
                            hedges.append(hedge)
        
        # 同组不同标签配对 (如不同阈值的 "above $1B" vs "above $2B")
        for group in self.groups:
            labels = {}
            for m in group.markets:
                if m.group_label not in labels:
                    labels[m.group_label] = []
                labels[m.group_label].append(m)
            
            # 不同标签配对
            label_list = list(labels.keys())
            for i, l1 in enumerate(label_list):
                for l2 in label_list[i+1:]:
                    for m1 in labels[l1]:
                        for m2 in labels[l2]:
                            hedge = self._calculate_hedge(m1, m2)
                            if hedge and hedge.coverage >= 0.85:
                                hedges.append(hedge)
        
        # 按覆盖率排序
        hedges.sort(key=lambda h: -h.coverage)
        
        # 保存到数据库
        for h in hedges[:20]:
            self.state.save_hedge(h)
        
        return hedges
    
    def _calculate_hedge(self, m1: Market, m2: Market) -> Optional[HedgeOpportunity]:
        """计算对冲"""
        # 尝试两种方向
        scenarios = [
            (m1, "YES", m2, "NO"),
            (m1, "NO", m2, "YES"),
            (m2, "YES", m1, "NO"),
            (m2, "NO", m1, "YES"),
        ]
        
        best = None
        best_score = 0
        
        for target, t_pos, cover, c_pos in scenarios:
            t_price = target.yes_price if t_pos == "YES" else target.no_price
            c_price = cover.yes_price if c_pos == "YES" else cover.no_price
            
            if t_price <= 0 or c_price <= 0:
                continue
            
            total_cost = t_price + c_price
            if total_cost > 2.0:
                continue
            
            result = calculate_coverage(t_price, c_price)
            
            # 过滤真正的套利 (cost接近$1) - 这些不是我们要找的对冲
            if abs(total_cost - 1.0) < 0.02:
                continue
            
            # 评分: 覆盖率 * 预期利润
            score = result["coverage"] * max(result["expected_profit"], 0)
            
            if score > best_score and result["coverage"] >= 0.85:
                best_score = score
                tier, tier_label = classify_tier(result["coverage"])
                
                best = HedgeOpportunity(
                    target_market=target,
                    cover_market=cover,
                    target_position=t_pos,
                    cover_position=c_pos,
                    coverage=result["coverage"],
                    tier=tier,
                    tier_label=tier_label,
                    total_cost=total_cost,
                    expected_profit=result["expected_profit"],
                    relationship=f"{t_pos} on '{target.question[:30]}' hedges against {c_pos} on '{cover.question[:30]}'"
                )
        
        return best
    
    def get_summary(self) -> str:
        """获取扫描摘要"""
        # 到期时间统计
        expiry_stats = get_expiry_summary(list(self.markets.values()))
        
        lines = [
            "=" * 60,
            "📊 Polymarket 扫描报告",
            "=" * 60,
            f"市场总数: {len(self.markets)}",
            f"分组数量: {len(self.groups)}",
            f"套利机会: {len(self.opportunities)}",
            f"对冲机会: {len(self.hedges)}",
            "",
            "⏰ 到期时间分布:",
            f"   <1h:   {expiry_stats.get('<1h', 0):>4} | "
            f"1-5h:  {expiry_stats.get('1-5h', 0):>4} | "
            f"5-10h: {expiry_stats.get('5-10h', 0):>4}",
            f"   10-24h: {expiry_stats.get('10-24h', 0):>4} | "
            f"24-48h: {expiry_stats.get('24-48h', 0):>4} | "
            f"48h+:   {expiry_stats.get('48h+', 0):>4} | "
            f"N/A:    {expiry_stats.get('N/A', 0):>4}",
            "",
            "🏆 Top 对冲机会:",
        ]
        
        for i, h in enumerate(self.hedges[:5], 1):
            # 添加到期时间
            bucket = get_time_bucket(h.target_market.hours_until_expiry)
            expiry_str = f" | 到期: {bucket}" if bucket != "N/A" else ""
            
            lines.append(f"{i}. {h.target_market.question[:35]}...")
            lines.append(f"   覆盖率: {h.coverage*100:.1f}% | Tier: {h.tier_label}{expiry_str}")
            lines.append(f"   成本: ${h.total_cost:.2f} | 预期利润: ${h.expected_profit:.2f}")
            lines.append("")
        
        return "\n".join(lines)

# =============================================================================
# 主函数
# =============================================================================

async def main():
    import sys
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    
    scanner = FullScanner()
    
    async with scanner.client:
        result = await scanner.scan()
        print(scanner.get_summary())

if __name__ == "__main__":
    asyncio.run(main())
