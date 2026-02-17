# Polymarket 跟单 Trader 库

> 最后更新: 2026-02-17 (v1.1)

## 统计

- 活跃交易员: **28**
- 已剔除: **5**

---

## A类: 短线/5-15分钟高频套利组

| # | Username | 地址 | 描述 | 来源 |
|---|----------|------|------|------|
| A1 | kingofcoinflips | - | 自动化脚本高手，单脚本$700K+ | @TGweb3333 |
| A2 | gabagool22 | - | 15分钟套利，日赚$10K | @TGweb3333 |
| A3 | 0x4460bf2c... | 0x4460bf2c0aa59db412a6493c2c08970797b62970 | 5分钟日赚$87K | @TGweb3333 |
| A4 | bbbbott | - | 5分钟加密市场早期玩家 | @TGweb3333 |
| A5 | 0x1d0034... | 0x1d0034134e339a309700ff2d34e99fa2d48b031 | $134→$192K传奇 | @TGweb3333 |
| A6 | planktonXD | - | $150→$104K | @TGweb3333 |

---

## B类: 天气/小众非对称赛道组

| # | Username | 地址 | 描述 |
|---|----------|------|------|
| B1 | 0x594edB... | 0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11 | 天气市场霸主，2月赚$30K+ |

---

## C类: NegRisk 类

| # | Username | 地址 | PnL | 状态 |
|---|----------|------|------|------|
| C1 | @xmgnr | 0xfdd9fc462c9d5913c11dce63e737cb4c7ab9f22a | $0 | inactive |
| C2 | @luishXYZ | 0x0da462636b228293849aac34c18577244775edde | $233 | active |
| C3 | @copenzafan | 0x95923e6dfa4e685361ffb0ead28657d3fa1aa85b | -$40K | active_losing |
| C4 | @carverfomo | 0x227b22b78b422bbad333bf903a164db3212916cf | $0 | inactive |
| C5 | @holy_moses7 | 0xa4b366ad22fc0d06f1e934ff468e8922431a87b8 | $2,578 | active |
| C6 | @PolycoolApp | 0x492442eab586f242b53bda933fd5de859c8a3782 | **$4.4M** | active |
| C7 | @itslirrato | 0x3adaadddf92874041363ba3db77e949bcb9f861a | $8 | active |

---

## D类: Basic / In-Market 类

| # | Username | 地址 | PnL | 状态 |
|---|----------|------|------|------|
| D1 | @clawdvine | 0x4de4d61565bbcc98605e4d53d0c6447a288e010a | $104 | active |
| D2 | @takecgcj | 0xce510458cc3964b1bb9aa9e2db28bb2b530bdda3 | $0 | inactive |
| D3 | @blknoiz06 | 0xc387de398cf17f60c9def1d35bb89c8bea05b0e4 | $1 | active |
| D4 | @cryptorover | 0x51f304b408809f398b4e565ce9190170e1617e7f | $499 | active |
| D5 | @SpotTheAnamoly | 0xc3e47dd79346216a72d1634fc8ed13d20658e7f9 | $2,581 | active |
| D6 | @AdiFlips | 0x41097a5a77840c970ffe62ce45b5b543784dad6b | $184 | active |

---

## E类: 独立分析标的

| # | Username | 地址 | PnL | 交易量 | 策略 |
|---|----------|------|------|--------|------|
| E1 | @0x8dxd | 0x63ce342161250d705dc0b16df89036c8e5f9ba9a | $1.5M | $128M | 做市套利机器人 |

---

## F类: BTC 5分钟高频套利组

来源: @qkl2058 推文

| # | Username | 地址 | PnL | 描述 |
|---|----------|------|------|------|
| F1 | MuseumOfBees | - | - | BTC 5分钟高频 |
| F2 | 0xe594336... | 0xe594336603f4fb5d3ba4125a67021ab3b4347052 | - | 盘口与现货同步延迟套利 |
| F3 | mqog1m | - | - | BTC 5分钟高频 |
| F4 | vague-sourdough | - | $58K | BTC 5分钟高频，持仓$16.9K |
| F5 | Demphu.finite | 0xd0bde12c58772999c61c2b8e0d31ba608c52a5d6 | $91K | BTC/ETH 5分钟，最大单笔$14.8K |
| F6 | 0x1979ae6b7e (OpenClaw) | 0x1979ae6b7e | $386K/月 | Fast-Loop策略，5ms套利窗口 |

---

## 已剔除 (5)

| Username | 原因 |
|----------|------|
| @sorokx | 404 |
| @zodchiii | 404 |
| @Zun2025 | 404 |
| @polytraderAI | 404 |
| @antpalkin | 404 |

---

## 监控配置

```bash
# 完整监控列表
MONITORED_WALLETS=0x4460bf2c0aa59db412a6493c2c08970797b62970,0x1d0034134e339a309700ff2d34e99fa2d48b031,0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11,0xfdd9fc462c9d5913c11dce63e737cb4c7ab9f22a,0x0da462636b228293849aac34c18577244775edde,0x95923e6dfa4e685361ffb0ead28657d3fa1aa85b,0xa4b366ad22fc0d06f1e934ff468e8922431a87b8,0x492442eab586f242b53bda933fd5de859c8a3782,0x3adaadddf92874041363ba3db77e949bcb9f861a,0x4de4d61565bbcc98605e4d53d0c6447a288e010a,0xc387de398cf17f60c9def1d35bb89c8bea05b0e4,0x51f304b408809f398b4e565ce9190170e1617e7f,0xc3e47dd79346216a72d1634fc8ed13d20658e7f9,0x41097a5a77840c970ffe62ce45b5b543784dad6b,0x63ce342161250d705dc0b16df89036c8e5f9ba9a,0xe594336603f4fb5d3ba4125a67021ab3b4347052,0xd0bde12c58772999c61c2b8e0d31ba608c52a5d6
```

---

## 跟单工具

| 工具 | 类型 | 链接 |
|------|------|------|
| PolyCop Bot | Telegram | t.me/PolyCop_BOT |
| Clawdbot | 自动化 | - |
| FrenFlow | 自建 | GitHub |
| Polycule.trade | Web | polycule.trade |

---

## 风险提醒

- 跟单核心风险是**延迟** (你常成 exit liquidity)
- 社区 **90%** 跟单者亏损
- 建议: 小额测试(<1%资金)、多元化跟3-5个trader
- 过去表现 ≠ 未来
