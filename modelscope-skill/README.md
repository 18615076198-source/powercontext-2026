# 魔搭 Skill 发布包（nearby-explorer）

本目录把仓库里的 nearby-explorer Skill 打包成符合魔搭技能中心要求的 zip：

- zip 根目录只有一份 SKILL.md（其余文件在 scripts/、fixtures/、examples/ 等子目录）；
- SKILL.md 的 frontmatter 含 name / version / description；
- 正文末尾会原样追加平台提测弹窗给出的验证行（独立一行）；
- zip ≤ 5MB（当前约 92KB）。

## 为什么需要两步输入

| 输入 | 从哪里来 | 用途 |
| --- | --- | --- |
| 验证行 | 提测弹窗「获取验证行」 | 追加到 SKILL.md 末尾，平台据此校验归属 |
| 魔搭 Access Token | https://modelscope.cn/my/myaccesstoken | 调用 OpenAPI 发布（或改用网页手动上传） |

## 打包

~~~bash
python build_skill.py --verify-line "把弹窗里的整行原样粘进来"
# 或把验证行存成文件（避免 shell 转义）
python build_skill.py --verify-line-file verify.txt
~~~

产物：dist/nearby-explorer-<hash>.zip 与同名 .manifest.json（sha256、大小、验证行）。

## 发布（二选一）

### A. 命令行发布

~~~bash
set MODELSCOPE_API_KEY=你的token         # PowerShell
python publish_skill.py --zip dist/nearby-explorer-<hash>.zip --owner 你的魔搭用户名
~~~

脚本会：上传 zip → 创建 Skill；若同名已存在则自动改为更新 skill_file。

### B. 网页手动发布

1. 打开 https://modelscope.cn/skills → 创建 Skill；
2. 上传 dist/nearby-explorer-<hash>.zip；
3. Skill 名称填 nearby-explorer，分类选「其他」，协议 MIT；
4. 发布后把作品链接（形如 https://modelscope.cn/skills/@用户名/nearby-explorer）填到提测表单。

## 发布后自检

~~~bash
# 公开详情（不带鉴权）
curl https://modelscope.cn/openapi/v1/skills/用户名/nearby-explorer

# 下载已发布包，确认 SKILL.md 末尾是验证行
curl -L -o published.zip https://www.modelscope.cn/skills/@用户名/nearby-explorer/archive/zip/master
unzip -p published.zip '*/SKILL.md' | tail -3
~~~
