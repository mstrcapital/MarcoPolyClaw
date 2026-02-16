"""
监控层 (Monitoring Layer)
=========================

功能:
- 实时日志记录
- Telegram 推送通知
- 每日汇总统计
- 仓位监控

支持:
- 日志 + Telegram 双通道
- 每日/每周报告
- PnL 追踪
"""

import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

# =============================================================================
# 配置
# =============================================================================

# Telegram 配置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 日志配置
LOG_FILE = os.getenv("LOG_FILE", "trading.log")
LOG_ROTATION = "100 MB"
LOG_RETENTION = "30 days"

# 报告配置
DAILY_REPORT_TIME = "09:00"  # 每天早上9点

# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    market_id: str
    question: str
    side: str
    size: float
    entry_price: float
    exit_price: Optional[float]
    pnl: float
    opened_at: datetime
    closed_at: Optional[datetime]
    status: str  # open, closed

@dataclass
class DailyReport:
    """每日报告"""
    date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    best_trade: float
    worst_trade: float
    open_positions: int

# =============================================================================
# Telegram 通知
# =============================================================================

class TelegramNotifier:
    """Telegram 通知"""
    
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
    
    async def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        """发送消息"""
        if not self.enabled:
            logger.info(f"[Telegram Disabled] {message}")
            return False
        
        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode
                })
            
            logger.info(f"📱 Telegram 消息已发送")
            return True
            
        except Exception as e:
            logger.error(f"❌ Telegram 发送失败: {e}")
            return False
    
    async def send_alert(self, title: str, message: str):
        """发送告警"""
        text = f"🚨 *{title}*\n\n{message}"
        await self.send(text)
    
    async def send_trade(self, trade: TradeRecord):
        """发送交易通知"""
        emoji = "✅" if trade.pnl > 0 else "❌" if trade.pnl < 0 else "📊"
        
        text = f"""
{emoji} *交易通知*

*市场:* {trade.question[:50]}...
*方向:* {trade.side}
*金额:* ${trade.size:.2f}
*入场:* ${trade.entry_price:.4f}
*出场:* ${trade.exit_price:.4f if trade.exit_price else 'N/A'}
*P&L:* ${trade.pnl:.2f}
"""
        await self.send(text)
    
    async def send_daily_report(self, report: DailyReport):
        """发送每日报告"""
        text = f"""
📊 *每日交易报告* - {report.date}

*交易统计:*
• 总交易: {report.total_trades}
• 胜: {report.winning_trades} | 负: {report.losing_trades}
• 胜率: {report.win_rate:.1f}%

*盈亏:*
• 总 PnL: ${report.total_pnl:.2f}
• 平均 PnL: ${report.avg_pnl:.2f}
• 最佳: ${report.best_trade:.2f}
• 最差: ${report.worst_trade:.2f}

*持仓:* {report.open_positions} 个仓位
"""
        await self.send(text)
    
    async def send_risk_alert(self, message: str):
        """发送风控告警"""
        await self.send_alert("⚠️ 风控告警", message)

# =============================================================================
# 交易记录管理器
# =============================================================================

class TradeRecorder:
    """交易记录管理"""
    
    def __init__(self, storage_file: str = "trades.json"):
        self.storage_file = storage_file
        self.trades: list[TradeRecord] = []
        self._load()
    
    def _load(self):
        """加载历史记录"""
        try:
            with open(self.storage_file, "r") as f:
                data = json.load(f)
                self.trades = [
                    TradeRecord(
                        trade_id=t["trade_id"],
                        market_id=t["market_id"],
                        question=t["question"],
                        side=t["side"],
                        size=t["size"],
                        entry_price=t["entry_price"],
                        exit_price=t.get("exit_price"),
                        pnl=t["pnl"],
                        opened_at=datetime.fromisoformat(t["opened_at"]),
                        closed_at=datetime.fromisoformat(t["closed_at"]) if t.get("closed_at") else None,
                        status=t["status"]
                    )
                    for t in data
                ]
        except FileNotFoundError:
            self.trades = []
        except Exception as e:
            logger.error(f"加载交易记录失败: {e}")
            self.trades = []
    
    def _save(self):
        """保存记录"""
        try:
            with open(self.storage_file, "w") as f:
                json.dump([
                    {
                        "trade_id": t.trade_id,
                        "market_id": t.market_id,
                        "question": t.question,
                        "side": t.side,
                        "size": t.size,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "pnl": t.pnl,
                        "opened_at": t.opened_at.isoformat(),
                        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                        "status": t.status
                    }
                    for t in self.trades
                ], f, indent=2)
        except Exception as e:
            logger.error(f"保存交易记录失败: {e}")
    
    def record_open(self, trade: TradeRecord):
        """记录开仓"""
        self.trades.append(trade)
        self._save()
    
    def record_close(self, trade_id: str, exit_price: float, pnl: float):
        """记录平仓"""
        for trade in self.trades:
            if trade.trade_id == trade_id:
                trade.exit_price = exit_price
                trade.pnl = pnl
                trade.closed_at = datetime.now()
                trade.status = "closed"
                break
        self._save()
    
    def get_open_trades(self) -> list[TradeRecord]:
        """获取开仓记录"""
        return [t for t in self.trades if t.status == "open"]
    
    def get_today_trades(self) -> list[TradeRecord]:
        """获取今日交易"""
        today = datetime.now().date()
        return [
            t for t in self.trades
            if t.opened_at.date() == today
        ]
    
    def get_daily_report(self, date: str = None) -> DailyReport:
        """获取每日报告"""
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = datetime.now().date()
        
        # 筛选当日交易
        day_trades = [
            t for t in self.trades
            if t.opened_at.date() == target_date and t.status == "closed"
        ]
        
        if not day_trades:
            return DailyReport(
                date=str(target_date),
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                total_pnl=0,
                avg_pnl=0,
                best_trade=0,
                worst_trade=0,
                open_positions=len(self.get_open_trades())
            )
        
        winning = [t for t in day_trades if t.pnl > 0]
        losing = [t for t in day_trades if t.pnl < 0]
        
        pnls = [t.pnl for t in day_trades]
        
        return DailyReport(
            date=str(target_date),
            total_trades=len(day_trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=len(winning) / len(day_trades) * 100,
            total_pnl=sum(pnls),
            avg_pnl=sum(pnls) / len(pnls),
            best_trade=max(pnls) if pnls else 0,
            worst_trade=min(pnls) if pnls else 0,
            open_positions=len(self.get_open_trades())
        )

# =============================================================================
# 监控器
# =============================================================================

class Monitor:
    """监控器"""
    
    def __init__(self, telegram_enabled: bool = False):
        self.notifier = TelegramNotifier() if telegram_enabled else None
        self.recorder = TradeRecorder()
        self.start_time = datetime.now()
    
    async def notify_trade(self, trade: TradeRecord):
        """通知交易"""
        if self.notifier:
            await self.notifier.send_trade(trade)
    
    async def notify_risk(self, message: str):
        """通知风控"""
        if self.notifier:
            await self.notifier.send_risk_alert(message)
    
    async def send_daily_report(self):
        """发送每日报告"""
        report = self.recorder.get_daily_report()
        
        if self.notifier:
            await self.notifier.send_daily_report(report)
        
        return report
    
    def get_status(self) -> dict:
        """获取状态"""
        open_trades = self.recorder.get_open_trades()
        
        return {
            "uptime": str(datetime.now() - self.start_time),
            "total_trades": len(self.recorder.trades),
            "open_positions": len(open_trades),
            "today_pnl": sum(t.pnl for t in self.recorder.get_today_trades()),
        }

# =============================================================================
# 示例
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    # 创建监控器
    monitor = Monitor(telegram_enabled=False)
    
    # 模拟交易记录
    trade = TradeRecord(
        trade_id="test_001",
        market_id="market_123",
        question="Will Bitcoin hit $100k by 2025?",
        side="YES",
        size=100,
        entry_price=0.85,
        exit_price=None,
        pnl=0,
        opened_at=datetime.now(),
        closed_at=None,
        status="open"
    )
    
    # 记录开仓
    monitor.recorder.record_open(trade)
    
    # 获取状态
    status = monitor.get_status()
    print(f"状态: {status}")
    
    # 获取每日报告
    report = monitor.recorder.get_daily_report()
    print(f"今日报告: {report}")
