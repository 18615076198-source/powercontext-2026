# 常用任务
PY ?= python
TASK ?= samples/task-001-report-region-filter/task.json

.PHONY: help install doctor demo test test-module test-demo flow clean

help:
	@echo "make install     安装依赖（Linux/macOS，含 seekdb 与 PowerContext）"
	@echo "make doctor      环境自检"
	@echo "make demo        一键复现完整流程（需要 PowerContext 已启动）"
	@echo "make test        模块测试 + 业务工程回归测试"
	@echo "make flow        只跑 import/plan/apply/verify/save/resume"
	@echo "make clean       删除本地索引与运行产物"

install:
	$(PY) -m pip install -r requirements.txt

doctor:
	PYTHONPATH=src $(PY) -m sddctx doctor

demo:
	./demo.sh

flow:
	PYTHONPATH=src $(PY) -m sddctx run --task $(TASK)

test: test-module test-demo

test-module:
	PYTHONPATH=src $(PY) -m pytest tests -q

test-demo:
	cd demo/billing-service && $(PY) -m pytest tests -q

clean:
	rm -rf .sddctx runs/*/context-pack.json runs/*/apply.json runs/*/verify.json
	rm -rf demo/billing-service/.sddctx
