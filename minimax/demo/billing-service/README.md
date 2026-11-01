# billing-service

一个用于演示「规格驱动开发（SDD）」的最小业务工程：会员折扣、订单校验、月度结算报表。

- 纯标准库实现，无第三方运行时依赖；测试用 `pytest`。
- 金额一律用「分」为单位的整数（BR-PRICE-01）。
- 规格在 `specs/`，每条 `BR-*` 都有对应测试。

## 运行测试

```bash
cd demo/billing-service
python -m pytest tests -q
```

## 目录

```
specs/    规格条目（每条 BR-* 可独立验证）
src/billing/
  models.py      订单/报表行模型
  pricing.py     优惠券 + 会员折扣
  validation.py  订单校验
  repository.py  JSON / 内存订单来源
  report.py      月度报表
tests/    回归测试
data/     JSON 样例订单
```
