# 魔搭 Skill 发布包（nearby-explorer）

本目录把仓库里的 nearby-explorer Skill 打包成符合魔搭技能中心要求的 zip。

## 发布状态

- 作品地址：https://modelscope.cn/skills/chenyongyu065/nearby-explorer
- 归属账号：chenyongyu065
- 公开：是（detail API private=false）
- 验证行：已附加在 SKILL.md 末尾，公开归档中可回读到
- 发布包：dist/nearby-explorer-6f21a799.zip（91.5KB，根目录仅 SKILL.md）

## 打包

~~~bash
python build_skill.py --verify-line "把弹窗里的整行原样粘进来"
# 或把验证行存成文件（避免 shell 转义）
python build_skill.py --verify-line-file verify.txt
~~~

产物：dist/nearby-explorer-<hash>.zip 与同名 .manifest.json（sha256、大小、验证行）。

## 本轮实际使用的命令

~~~bash
set MODELSCOPE_API_KEY=<token>
python publish_skill.py --zip dist/nearby-explorer-6f21a799.zip --owner chenyongyu065 --name nearby-explorer --category other --license "MIT License"
~~~

## 发布后核验

~~~bash
# 公开详情
curl https://modelscope.cn/openapi/v1/skills/chenyongyu065/nearby-explorer

# 公开归档里的 SKILL.md 末尾
curl -L -o p.zip https://modelscope.cn/skills/chenyongyu065/nearby-explorer/archive/zip/master
unzip -p p.zip '*/SKILL.md' | tail -3
~~~
