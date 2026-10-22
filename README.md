# Pexels 图片搜索技能

用自己的 Pexels API Key 搜索照片，查看编号候选图册，选定后按照片 ID 下载原图，同时保存作者、来源、尺寸和 SHA-256。你可以把它作为 Codex 技能使用，也可以直接运行 Python 命令。

**版本 1.1.1** 精简了技能说明，沿用 1.1.0 的实现、配置方式和测试。

## 环境与安装

需要 Python **3.11+**，并确保 `python` 命令指向对应的解释器。搜索还需要网络和自己的 [Pexels API Key](https://www.pexels.com/api/)。依赖版本写在 [requirements.txt](requirements.txt) 中：Requests 2.34.2、Pillow 13.0.0。

解压或克隆后，进入包含 `SKILL.md` 的目录，运行：

```text
python -m pip install --target _vendor -r requirements.txt
```

依赖会安装到当前目录下的 `_vendor`。

如果还没有配置文件，就把 [.env.example](.env.example) 复制为 `.env`，然后用本地编辑器填写：

```dotenv
PEXELS_API_KEY=YOUR_PEXELS_API_KEY
```

示例中的值是占位符，请换成自己的密钥。不要将实际密钥放进 GitHub、Issue、截图或日志，也不要覆盖已有 `.env`。环境变量、指定配置文件及读取顺序见 [CLI 配置](references/cli.md#配置)。

```text
python scripts/pexels_search.py doctor
python scripts/pexels_search.py doctor --live
```

普通诊断只检查配置和依赖；加上 `--live` 后，会用一次真实请求检查联网和认证。

如果要作为 Codex 技能使用，请把整个目录放到你配置的技能目录中，保留根目录下的 `SKILL.md`，再在新聊天中调用 `$pexels-image-search`。

## 最短用法

```text
python scripts/pexels_search.py search "offshore wind farm" --output outputs --orientation landscape --min-width 1920 --min-height 1080 --per-page 8
```

打开输出目录中的 `review_sheet_*.jpg` 或预览图片，选好要下载的照片。把下面的路径和照片 ID 换成实际搜索结果：

```text
python scripts/pexels_search.py download --candidates "outputs/search-实际目录/candidates.json" --id 123456 --output outputs/selected --selection-method user-selected
```

下载后，请将原图和 `image_sources.json` 一起保存。选择方式见 [技能流程](SKILL.md#流程)，完整参数、输出文件和失败后的处理方式见 [CLI 文档](references/cli.md)。

## 测试与适用范围

```text
python -B -m unittest discover -s tests -p "test_*.py" -v
```

67 项离线测试在测试目录中模拟网络请求。Windows / Python 3.14 已完成这些测试，并完成真实搜索和下载验证。Python 最低版本由代码使用的 `hashlib.file_digest` 和 [Pillow 13](https://pypi.org/project/pillow/13.0.0/)共同决定。