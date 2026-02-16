"""
缓存层 (Cache Layer)
==================

功能:
- 市场数据缓存
- 价格缓存
- 订单簿缓存
- TTL 过期

支持:
- Redis (生产)
- 内存缓存 (开发/备用)
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from loguru import logger

# =============================================================================
# 配置
# =============================================================================

REDIS_URL = os.getenv("REDIS_URL", "")
CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))  # 默认 30 秒
USE_REDIS = bool(REDIS_URL)

# =============================================================================
# 缓存条目
# =============================================================================

@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float
    ttl: int  # 秒
    
    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl
    
    @property
    def age(self) -> float:
        return time.time() - self.created_at

# =============================================================================
# 内存缓存
# =============================================================================

class MemoryCache:
    """内存缓存 (备用)"""
    
    def __init__(self):
        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """获取"""
        async with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired:
                return entry.value
            elif entry:
                del self._cache[key]
            return None
    
    async def set(self, key: str, value: Any, ttl: int = CACHE_TTL):
        """设置"""
        async with self._lock:
            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl
            )
    
    async def delete(self, key: str):
        """删除"""
        async with self._lock:
            self._cache.pop(key, None)
    
    async def clear(self):
        """清空"""
        async with self._lock:
            self._cache.clear()
    
    async def cleanup(self):
        """清理过期"""
        async with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired]
            for k in expired:
                del self._cache[k]
    
    async def get_stats(self) -> dict:
        """统计"""
        async with self._lock:
            total = len(self._cache)
            expired = sum(1 for v in self._cache.values() if v.is_expired)
            return {
                "total": total,
                "expired": expired,
                "active": total - expired
            }

# =============================================================================
# Redis 缓存
# =============================================================================

class RedisCache:
    """Redis 缓存 (生产)"""
    
    def __init__(self, url: str):
        self.url = url
        self._client = None
        self._connected = False
    
    async def connect(self):
        """连接"""
        try:
            import aioredis
            self._client = await aioredis.create_redis_pool(self.url)
            self._connected = True
            logger.info("✅ Redis 已连接")
        except Exception as e:
            logger.error(f"❌ Redis 连接失败: {e}")
            self._connected = False
    
    async def close(self):
        """关闭"""
        if self._client:
            self._client.close()
            self._connected = False
    
    async def get(self, key: str) -> Optional[Any]:
        """获取"""
        if not self._connected:
            return None
        
        try:
            value = await self._client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get 错误: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = CACHE_TTL):
        """设置"""
        if not self._connected:
            return
        
        try:
            await self._client.set(
                key,
                json.dumps(value),
                expire=ttl
            )
        except Exception as e:
            logger.error(f"Redis set 错误: {e}")
    
    async def delete(self, key: str):
        """删除"""
        if not self._connected:
            return
        
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.error(f"Redis delete 错误: {e}")
    
    async def clear(self):
        """清空"""
        if not self._connected:
            return
        
        try:
            await self._client.flushdb()
        except Exception as e:
            logger.error(f"Redis clear 错误: {e}")
    
    async def get_stats(self) -> dict:
        """统计"""
        if not self._connected:
            return {"connected": False}
        
        try:
            info = await self._client.info("stats")
            return {
                "connected": True,
                "keys": await self._client.dbsize()
            }
        except:
            return {"connected": False}

# =============================================================================
# 统一缓存接口
# =============================================================================

class Cache:
    """统一缓存接口"""
    
    def __init__(self):
        self._cache = None
        self._use_redis = False
    
    async def init(self):
        """初始化"""
        if USE_REDIS and REDIS_URL:
            self._cache = RedisCache(REDIS_URL)
            await self._cache.connect()
            self._use_redis = True
            logger.info("使用 Redis 缓存")
        else:
            self._cache = MemoryCache()
            logger.info("使用内存缓存")
    
    async def close(self):
        """关闭"""
        if self._use_redis and self._cache:
            await self._cache.close()
    
    async def get(self, key: str) -> Optional[Any]:
        """获取"""
        return await self._cache.get(key)
    
    async def set(self, key: str, value: Any, ttl: int = CACHE_TTL):
        """设置"""
        await self._cache.set(key, value, ttl)
    
    async def delete(self, key: str):
        """删除"""
        await self._cache.delete(key)
    
    async def clear(self):
        """清空"""
        await self._cache.clear()
    
    async def get_market(self, market_id: str) -> Optional[dict]:
        """获取市场数据"""
        return await self.get(f"market:{market_id}")
    
    async def set_market(self, market_id: str, data: dict, ttl: int = CACHE_TTL):
        """设置市场数据"""
        await self.set(f"market:{market_id}", data, ttl)
    
    async def get_price(self, token_id: str) -> Optional[float]:
        """获取价格"""
        data = await self.get(f"price:{token_id}")
        return data.get("price") if data else None
    
    async def set_price(self, token_id: str, price: float, ttl: int = 10):
        """设置价格 (短 TTL)"""
        await self.set(f"price:{token_id}", {"price": price, "updated_at": time.time()}, ttl)
    
    async def get_orderbook(self, token_id: str) -> Optional[dict]:
        """获取订单簿"""
        return await self.get(f"orderbook:{token_id}")
    
    async def set_orderbook(self, token_id: str, data: dict, ttl: int = 5):
        """设置订单簿 (短 TTL)"""
        await self.set(f"orderbook:{token_id}", data, ttl)
    
    async def get_stats(self) -> dict:
        """统计"""
        return await self._cache.get_stats()

# =============================================================================
# 市场数据缓存助手
# =============================================================================

class MarketCacheHelper:
    """市场数据缓存助手"""
    
    def __init__(self, cache: Cache):
        self.cache = cache
    
    async def get_or_fetch_market(self, market_id: str, fetch_func) -> dict:
        """获取或获取市场数据"""
        # 尝试缓存
        cached = await self.cache.get_market(market_id)
        if cached:
            logger.debug(f"缓存命中: {market_id}")
            return cached
        
        # 获取新数据
        logger.debug(f"缓存未命中: {market_id}")
        data = await fetch_func(market_id)
        
        if data:
            await self.cache.set_market(market_id, data)
        
        return data
    
    async def get_or_fetch_price(self, token_id: str, fetch_func) -> float:
        """获取或获取价格"""
        # 尝试缓存
        cached = await self.cache.get_price(token_id)
        if cached:
            return cached
        
        # 获取新数据
        price = await fetch_func(token_id)
        
        if price:
            await self.cache.set_price(token_id, price)
        
        return price

# =============================================================================
# 示例
# =============================================================================

if __name__ == "__main__":
    async def main():
        # 创建缓存
        cache = Cache()
        await cache.init()
        
        # 测试
        await cache.set("test_key", {"data": "hello"}, ttl=10)
        value = await cache.get("test_key")
        print(f"Value: {value}")
        
        # 市场数据
        await cache.set_market("0x123", {"question": "Test?"})
        market = await cache.get_market("0x123")
        print(f"Market: {market}")
        
        # 价格
        await cache.set_price("token123", 0.85)
        price = await cache.get_price("token123")
        print(f"Price: {price}")
        
        # 统计
        stats = await cache.get_stats()
        print(f"Stats: {stats}")
        
        await cache.close()
    
    asyncio.run(main())
