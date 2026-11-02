#!/usr/bin/env python3
"""把打包好的 Skill zip 发布到魔搭（ModelScope）技能中心。

两步（官方 OpenAPI）：
  1. POST /openapi/v1/files/upload   multipart(file, type=skill) -> data.id
  2. POST /openapi/v1/skills         创建；已存在则 PATCH /skills/{owner}/{name}/settings 更新

鉴权：MODELSCOPE_API_KEY（https://modelscope.cn/my/myaccesstoken）
用法：
  python publish_skill.py --zip dist/xxx.zip --owner 你的用户名 --dry-run
  python publish_skill.py --zip dist/xxx.zip --owner 你的用户名
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests", file=sys.stderr)
    raise SystemExit(1)


def api_base(endpoint: str) -> str:
    return endpoint.rstrip("/") + "/openapi/v1"


def upload(endpoint: str, token: str, zip_path: Path) -> str:
    with open(zip_path, "rb") as handle:
        resp = requests.post(
            api_base(endpoint) + "/files/upload",
            headers={"Authorization": "Bearer " + token},
            files={"file": (zip_path.name, handle, "application/zip")},
            data={"type": "skill"},
            timeout=120,
        )
    payload = resp.json()
    if resp.status_code != 200 or not payload.get("success"):
        raise RuntimeError("上传失败: HTTP %s %s" % (resp.status_code, json.dumps(payload, ensure_ascii=False)[:400]))
    return payload["data"]["id"]


def create_skill(endpoint: str, token: str, meta: dict) -> dict:
    resp = requests.post(
        api_base(endpoint) + "/skills",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        json=meta,
        timeout=120,
    )
    return {"status": resp.status_code, "body": resp.json()}


def update_skill(endpoint: str, token: str, owner: str, name: str, meta: dict) -> dict:
    resp = requests.patch(
        api_base(endpoint) + "/skills/%s/%s/settings" % (owner, name),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        json=meta,
        timeout=120,
    )
    return {"status": resp.status_code, "body": resp.json()}


def main() -> int:
    parser = argparse.ArgumentParser(description="发布 Skill 到魔搭")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--owner", default=os.environ.get("MODELSCOPE_OWNER", ""))
    parser.add_argument("--name", default="nearby-explorer")
    parser.add_argument("--display-name", default="周边去哪儿 nearby-explorer")
    parser.add_argument("--description", default="一句话找到附近 3~5 个去处，并给出步行/骑行/公交/驾车方案与高德跳转链接。")
    parser.add_argument("--category", default="developer-tools")
    parser.add_argument("--license", default="MIT License")
    parser.add_argument("--tags", default="amap,location,recommendation")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--endpoint", default=os.environ.get("MODELSCOPE_ENDPOINT", "https://modelscope.cn"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.is_file():
        print("找不到 zip: " + str(zip_path), file=sys.stderr)
        return 1
    if not args.owner:
        print("缺少 --owner（魔搭用户名，例如 @ 后面的部分）", file=sys.stderr)
        return 1

    token = os.environ.get("MODELSCOPE_API_KEY", "")
    if args.dry_run or not token:
        print("== 发布参数 ==")
        print(json.dumps({
            "owner": args.owner,
            "skill_name": args.name,
            "display_name": args.display_name,
            "description": args.description,
            "category": args.category,
            "license": args.license,
            "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
            "source_url": args.source_url,
            "endpoint": args.endpoint,
            "zip": str(zip_path),
        }, ensure_ascii=False, indent=2))
        print("\n== 等价 curl ==")
        print('curl -X POST "$MODELSCOPE_ENDPOINT/openapi/v1/files/upload" \\')
        print('  -H "Authorization: Bearer $MODELSCOPE_API_KEY" \\')
        print('  -F "file=@%s" -F "type=skill"' % zip_path)
        print('curl -X POST "$MODELSCOPE_ENDPOINT/openapi/v1/skills" \\')
        print('  -H "Authorization: Bearer $MODELSCOPE_API_KEY" -H "Content-Type: application/json" \\')
        print('  -d \'{"owner":"%s","skill_name":"%s","display_name":"%s","skill_file":"<上一步 data.id>","category":"%s","license":"%s"}\''
              % (args.owner, args.name, args.display_name, args.category, args.license))
        if not token:
            print("\n[提示] 未设置 MODELSCOPE_API_KEY，仅打印参数；设置后执行正式发布。")
        return 0

    file_id = upload(args.endpoint, token, zip_path)
    print("[1/2] 上传成功 file_id=" + file_id)

    meta = {
        "owner": args.owner,
        "skill_name": args.name,
        "display_name": args.display_name,
        "description": args.description,
        "skill_file": file_id,
        "category": args.category,
        "license": args.license,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
    }
    if args.source_url:
        meta["source_url"] = args.source_url

    result = create_skill(args.endpoint, token, meta)
    body = result["body"]
    if result["status"] == 200 and body.get("success"):
        print("[2/2] 创建成功: https://modelscope.cn/skills/@%s/%s" % (args.owner, args.name))
        print(json.dumps(body.get("data", {}), ensure_ascii=False)[:600])
        return 0

    message = json.dumps(body, ensure_ascii=False)
    if any(word in message.lower() for word in ("exist", "conflict", "duplicate")):
        print("[2/2] 已存在，改为更新 skill_file …")
        update_meta = {"skill_file": file_id, "description": args.description, "tags": meta["tags"]}
        updated = update_skill(args.endpoint, token, args.owner, args.name, update_meta)
        if updated["status"] == 200 and updated["body"].get("success"):
            print("更新成功: https://modelscope.cn/skills/@%s/%s" % (args.owner, args.name))
            return 0
        print("更新失败: " + json.dumps(updated, ensure_ascii=False)[:600], file=sys.stderr)
        return 1

    print("创建失败: HTTP %s %s" % (result["status"], message[:600]), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
