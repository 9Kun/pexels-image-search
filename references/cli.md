# CLI 与故障处理

运行入口是 `python "<SKILL_DIR>/scripts/pexels_search.py"`，下面的参数都接在它后面，路径需加引号。正常执行子命令时输出 UTF-8 JSON，帮助信息和参数错误则输出文本。请结合退出码和返回的实际状态判断是否成功。

## 配置

需要 Python ≥3.11。缺少依赖时运行：

```text
python -m pip install --target "<SKILL_DIR>/_vendor" -r "<SKILL_DIR>/requirements.txt"
```

先到 [Pexels API 官网](https://www.pexels.com/api/)申请自己的 Key。如果还没有配置文件，把 `.env.example` 复制为 `.env`，再在本机填写。也可以设置进程环境变量 `PEXELS_API_KEY`，或通过 `--env-file PATH` 指定文件。发布时不要包含私有配置、依赖、日志和输出文件。

密钥按这个顺序读取：进程环境变量 → 显式指定的配置文件 → 技能根目录下的 `.env`。如果已有有效的进程环境变量，就直接使用；否则，显式指定的文件必须可读且包含有效 Key，出错时不会回退到其他文件。环境变量和文件中的 Key 都不能使用占位符、控制字符或无效空白。

`doctor [--live] [--env-file PATH]` 检查配置和依赖，只有加上 `--live` 才会执行一次真实 API 搜索并消耗额度。

## 搜索

```text
search QUERY --output DIR [--orientation any|landscape|portrait|square] [--min-width N --min-height N --page N --per-page N] [--env-file PATH]
```

方向默认为 `any`，最低宽高为 `0`，从第 `1` 页开始，每页 `20` 张，最多可设为 `80` 张。搜索使用真实 API 分页，按返回顺序保留结果，再按原图尺寸筛选。筛选后不足一页时不会补图，API 总结果数不代表筛选后的数量。需要下一页时，增大 `--page`。

结果保存在 `DIR/search-<timestamp>-<random>/`，其中有 `candidates.json`、`previews/` 和每册最多 8 张图的 `review_sheet_*.jpg`。预览优先使用 medium，其次使用 small；预览失败会记录在 JSON 中。成功响应中有效的额度信息保存在 `rate_limit`，reset 使用 UNIX 时间。

## 下载

```text
download --candidates PATH --id ID [--id ID ...] --output DIR [--selection-method METHOD]
```

选择方式见 [技能流程](../SKILL.md#流程)。下载直接使用候选中的原图链接。文件扩展名根据实际图片格式确定，下载内容保留原始响应字节，并按图片实际显示的尺寸和方向复核筛选条件。

候选文件须使用版本 1，照片 ID 必须是互不重复的正整数，筛选参数也必须有效。原图和来源页须与候选照片的 ID 一致，来源页和摄影师链接须使用官方 HTTPS 地址。`visual-reviewed` 要求预览文件保存在候选目录内、确实存在且可以解码；新生成的候选还会校验 `preview_sha256`。移动候选时，请一并移动预览目录。

下载会拒绝重复 ID 和同名目标。追加图片前，会核对已有清单和图片的字节数、SHA-256。单个文件上限为 256 MiB，最多逐帧验证 64 帧，累计不超过 89,478,485 像素。程序能捕获的异常和中断会触发本批次回滚。发现残留锁时，先确认旧任务已经结束，再处理锁文件。

请将 `image_sources.json` 和图片一起交付、保存。清单中记录了作者、来源、许可、选择方式、实际尺寸、字节数和 SHA-256。

## 失败处理

返回 401 时检查本机 Key；返回 429 时等待额度恢复。超时或校验失败时，应如实报告。重试时保留原来的查询词和筛选条件。依赖安装及发布方法见 [README](../README.md)；许可和 API 规范链接见 [SKILL.md](../SKILL.md#边界)。
