# Polymarket 跟单 Trader 库

> 最后更新: 2026-02-17

## 1. 短线/5-15分钟高频套利组

| # | Trader | 地址 | Profile | 描述 |
|---|--------|------|---------|------|
| 1 | kingofcoinflips | - | polymarket.com/profile/kingofcoinflips | 自动化脚本高手，单脚本赚70万美元+ |
| 2 | gabagool22 | - | polymarket.com/profile/gabagool22 | 15分钟套利专家，一天赚1万美元 |
| 3 | 0x4460bf2c | 0x4460bf2c0aa59db412a6493c2c08970797b62970 | polymarket.com/profile/0x4460bf2c0aa59db412a6493c2c08970797b62970 | 5分钟市场一天赚8.7万美元 |
| 4 | bbbbott | - | polymarket.com/profile/bbbbott | 5分钟加密市场早期玩家 |
| 5 | 0x1d0034 | 0x1d0034134e339a309700ff2d34e99fa2d48b031 | polymarket.com/profile/0x1d0034134e339a309700ff2d34e99fa2d48b031 | 一天从134美元到192k美元 |
| 6 | planktonXD | - | polymarket.com/profile/planktonXD | 从150美元到10.4万美元 |

## 2. 天气/小众非对称赛道组

| # | Trader | 地址 | Profile | 描述 |
|---|--------|------|---------|------|
| 1 | 0x594edB | 0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11 | polymarket.com/profile/0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11 | 天气市场霸主，两个月赚3万美元+ |

## 3. 著名交易员地址 (完整)

### 高频套利
- `0x4460bf2c0aa59db412a6493c2c08970797b62970` - 5分钟市场专家
- `0x1d0034134e339a309700ff2d34e99fa2d48b031` - 134→192k 传奇
- `0xbBbbbTt` - bbbbott (可能地址)

### 天气/长线
- `0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11` - 天气市场

### 待确认
- kingofcoinflips
- gabagool22
- planktonXD

## 4. 跟单工具

- **PolyCop Bot**: t.me/PolyCop_BOT
- **Clawdbot**: 高频algo兼容
- **FrenFlow**: 高级用户

## 5. 监控配置

```python
# 监控列表
MONITORED_TRADERS = [
    "0x4460bf2c0aa59db412a6493c2c08970797b62970",
    "0x1d0034134e339a309700ff2d34e99fa2d48b031",
    "0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11",
]
```

## 6. 风险提醒

- 跟单核心风险是延迟 (你常成 exit liquidity)
- 社区90%跟单者亏损
- 建议: 小额测试(<1%资金)、多元化跟3-5个trader
- 过去表现 ≠ 未来
