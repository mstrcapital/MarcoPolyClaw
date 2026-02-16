"""
交易队列层 (Trade Queue)
==================

功能:
- 策略与执行解耦
- 异步交易处理
- 交易优先级
- 队列持久化

架构:
- TradeQueue: 交易队列管理器
- TradeWorker: 交易处理工作器
- PriorityQueue: 优先级队列
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from loguru import logger
from enum import Enum

# =============================================================================
# 配置
# =============================================================================

QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", "100"))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "2"))
QUEUE_TIMEOUT = int(os.getenv("QUEUE_TIMEOUT", "60"))

# =============================================================================
# 数据模型
# =============================================================================

class TradePriority(Enum):
    """交易优先级"""
    HIGH = 1    # 高优先级 (大额/鲸鱼信号)
    NORMAL = 2   # 正常
    LOW = 3      # 低优先级

@dataclass
class QueuedTrade:
    """队列交易"""
    trade_id: str
    market_id: str
    question: str
    side: str
    amount: float
    price: float
    priority: TradePriority = TradePriority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)
    retries: int = 0
    max_retries: int = 3
    status: str = "pending"  # pending, processing, completed, failed
    
    @property
    def is_retryable(self) -> bool:
        return self.retries < self.max_retries

# =============================================================================
# 交易队列
# =============================================================================

class TradeQueue:
    """交易队列"""
    
    def __init__(self, max_size: int = QUEUE_MAX_SIZE):
        self.max_size = max_size
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_size)
        self._trades: dict[str, QueuedTrade] = {}
        self._lock = asyncio.Lock()
        
        logger.info(f"交易队列初始化: 最大 {max_size} 个")
    
    async def enqueue(self, trade: QueuedTrade) -> bool:
        """入队"""
        async with self._lock:
            # 检查是否已存在
            if trade.trade_id in self._trades:
                logger.warning(f"交易已存在: {trade.trade_id}")
                return False
            
            # 检查队列是否满
            if self._queue.full():
                logger.warning("队列已满")
                return False
            
            # 入队
            self._trades[trade.trade_id] = trade
            await self._queue.put((trade.priority.value, trade))
            
            logger.info(f"✅ 入队: {trade.trade_id} (优先级: {trade.priority.name})")
            return True
    
    async def dequeue(self, timeout: float = None) -> Optional[QueuedTrade]:
        """出队"""
        try:
            priority, trade = await asyncio.wait_for(
                self._queue.get(),
                timeout=timeout
            )
            trade.status = "processing"
            return trade
        except asyncio.TimeoutError:
            return None
    
    async def get_status(self, trade_id: str) -> Optional[QueuedTrade]:
        """获取交易状态"""
        async with self._lock:
            return self._trades.get(trade_id)
    
    async def mark_completed(self, trade_id: str):
        """标记完成"""
        async with self._lock:
            if trade_id in self._trades:
                self._trades[trade_id].status = "completed"
    
    async def mark_failed(self, trade_id: str, retry: bool = False):
        """标记失败"""
        async with self._lock:
            if trade_id in self._trades:
                trade = self._trades[trade_id]
                if retry and trade.is_retryable:
                    trade.retries += 1
                    trade.status = "pending"
                    await self._queue.put((trade.priority.value, trade))
                    logger.info(f"🔄 重试交易: {trade_id} (尝试 {trade.retries})")
                else:
                    trade.status = "failed"
                    logger.error(f"❌ 交易失败: {trade_id}")
    
    async def get_stats(self) -> dict:
        """获取统计"""
        async with self._lock:
            stats = {
                "total": len(self._trades),
                "pending": sum(1 for t in self._trades.values() if t.status == "pending"),
                "processing": sum(1 for t in self._trades.values() if t.status == "processing"),
                "completed": sum(1 for t in self._trades.values() if t.status == "completed"),
                "failed": sum(1 for t in self._trades.values() if t.status == "failed"),
            }
            return stats

# =============================================================================
# 交易工作器
# =============================================================================

class TradeWorker:
    """交易工作器"""
    
    def __init__(self, worker_id: int, queue: TradeQueue, executor):
        self.worker_id = worker_id
        self.queue = queue
        self.executor = executor
        self._running = False
        self._task = None
    
    async def start(self):
        """启动工作器"""
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(f"工作器 {self.worker_id} 启动")
    
    async def stop(self):
        """停止工作器"""
        self._running = False
        if self._task:
            await self._task
        logger.info(f"工作器 {self.worker_id} 停止")
    
    async def _run(self):
        """工作循环"""
        while self._running:
            try:
                # 出队
                trade = await self.queue.dequeue(timeout=1)
                
                if not trade:
                    continue
                
                logger.info(f"工作器 {self.worker_id} 处理: {trade.trade_id}")
                
                # 执行交易
                result = await self._execute_trade(trade)
                
                if result.get("success"):
                    await self.queue.mark_completed(trade.trade_id)
                    logger.info(f"✅ 完成: {trade.trade_id}")
                else:
                    # 重试或失败
                    await self.queue.mark_failed(trade.trade_id, retry=trade.is_retryable)
                    
            except Exception as e:
                logger.error(f"工作器错误: {e}")
                await asyncio.sleep(1)
    
    async def _execute_trade(self, trade: QueuedTrade) -> dict:
        """执行交易"""
        try:
            # 调用执行器
            result = await self.executor(
                market_id=trade.market_id,
                side=trade.side,
                amount=trade.amount,
                price=trade.price
            )
            return result
        except Exception as e:
            logger.error(f"执行失败: {e}")
            return {"success": False, "error": str(e)}

# =============================================================================
# 交易队列管理器
# =============================================================================

class TradeQueueManager:
    """交易队列管理器"""
    
    def __init__(self, executor, worker_count: int = WORKER_COUNT):
        self.queue = TradeQueue()
        self.workers: list[TradeWorker] = []
        self.executor = executor
        self.worker_count = worker_count
        self._running = False
    
    async def start(self):
        """启动管理器"""
        self._running = True
        
        # 创建工作器
        for i in range(self.worker_count):
            worker = TradeWorker(i + 1, self.queue, self.executor)
            self.workers.append(worker)
            await worker.start()
        
        logger.info(f"交易队列管理器启动: {self.worker_count} 个工作器")
    
    async def stop(self):
        """停止管理器"""
        self._running = False
        
        for worker in self.workers:
            await worker.stop()
        
        logger.info("交易队列管理器停止")
    
    async def submit_trade(self, market_id: str, question: str, side: str,
                         amount: float, price: float, 
                         priority: TradePriority = TradePriority.NORMAL) -> str:
        """提交交易"""
        import uuid
        trade_id = str(uuid.uuid4())[:8]
        
        trade = QueuedTrade(
            trade_id=trade_id,
            market_id=market_id,
            question=question,
            side=side,
            amount=amount,
            price=price,
            priority=priority
        )
        
        await self.queue.enqueue(trade)
        
        return trade_id
    
    async def get_status(self, trade_id: str) -> Optional[QueuedTrade]:
        """获取交易状态"""
        return await self.queue.get_status(trade_id)
    
    async def get_stats(self) -> dict:
        """获取统计"""
        queue_stats = await self.queue.get_stats()
        return {
            "queue": queue_stats,
            "workers": self.worker_count,
            "running": self._running
        }

# =============================================================================
# 示例
# =============================================================================

if __name__ == "__main__":
    async def mock_executor(market_id, side, amount, price):
        """模拟执行器"""
        await asyncio.sleep(1)
        return {"success": True, "tx_hash": "0x123..."}
    
    async def main():
        # 创建管理器
        manager = TradeQueueManager(executor=mock_executor, worker_count=2)
        await manager.start()
        
        # 提交交易
        trade_id = await manager.submit_trade(
            market_id="0x123",
            question="Will BTC hit $100k?",
            side="YES",
            amount=100,
            price=0.85,
            priority=TradePriority.HIGH
        )
        
        print(f"Submitted: {trade_id}")
        
        # 等待
        await asyncio.sleep(3)
        
        # 获取状态
        status = await manager.get_status(trade_id)
        print(f"Status: {status}")
        
        # 统计
        stats = await manager.get_stats()
        print(f"Stats: {stats}")
        
        await manager.stop()
    
    asyncio.run(main())
