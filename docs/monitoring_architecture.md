# 链上事件监听技术方案

> 最后更新: 2026-02-17

## 核心思路

监控目标地址 → 链上事件监听

## 技术实现路径

### 1. Web3/WebSocket 订阅
- 使用 Web3.js 或 ethers.js 订阅链上事件 (Transfer, Trade)
- 监听目标地址的交易流入/流出
- 优点: 延迟低，能在交易进入 mempool 时就发现

### 2. Polymarket Data API
- 直接查询某个地址的持仓、交易记录
- GET /positions?user=0x... 获取仓位情况

### 3. 参考代码库

| 项目 | 技术栈 | 功能 | 适用场景 |
|------|--------|------|----------|
| crellOS/polymarket-tracking-bot | Rust | 监控账户交易行为，自动跟单 | Polymarket，低延迟 |
| tianheil3/polymarket-monitor | Python/JS | 实时监控市场趋势、交易量 | 市场分析 |
| Aboudjem/web3-listener | TypeScript | WebSocket 监听 ETH 转账和交易 | 通用链上事件 |
| tssandor/ETHWatchBot | Node.js | Telegram bot 监控指定地址 | 轻量化通知 |

## 推荐组合方案

- **数据源**: Polymarket Data API + WebSocket 监听
- **执行框架**: polymarket-tracking-bot (Rust)
- **通知机制**: ETHWatchBot (Telegram)
- **扩展性**: web3-listener (WebSocket-only)

## TODO

- [ ] 实现 WebSocket 实时监听
- [ ] 整合 Telegram 推送
- [ ] 优化延迟 (目标 < 100ms)
