# OpenClaw Handbook Export

这是一个用于维护和导出 OpenClaw 手册的项目。

项目内容以 Markdown 章节为源文件，通过 Node.js 脚本渲染为整本 HTML，并可继续导出为 PDF。

## 目录结构

```text
openclaw-work/
├─ docs/
│  ├─ handbook/
│  │  ├─ assets/
│  │  ├─ chapters/
│  │  └─ handbook.config.json
│  └─ references/
│     └─ pdfs/            # 本地参考资料，已加入 .gitignore，不推送
├─ scripts/
│  ├─ render-handbook.mjs
│  └─ pdf_to_md.py
├─ package.json
└─ README.md
```

## 环境要求

- Node.js
- npm
- Chrome 或 Edge

导出 PDF 时，脚本会优先使用环境变量 `BROWSER_PATH` 指定的浏览器路径；未设置时，会自动尝试常见的 Chrome / Edge 安装路径。

## 常用命令

安装依赖：

```powershell
npm install
```

导出 HTML 和 PDF：

```powershell
npm run build:handbook
```

只导出 HTML：

```powershell
npm run build:handbook:html
```

只导出 PDF：

```powershell
npm run build:handbook:pdf
```

兼容别名命令：

```powershell
npm run handbook
npm run handbook:html
npm run handbook:pdf
```

## 参考 PDF 转 Markdown

项目内保留了一个无需额外第三方依赖的 PDF 转 Markdown 脚本，可用于把本地参考 PDF 粗转换为 Markdown：

```powershell
python scripts/pdf_to_md.py "docs/references/pdfs/your-file.pdf" -o dist/converted-md
```

批量转换示例：

```powershell
python scripts/pdf_to_md.py docs/references/pdfs/*.pdf -o dist/converted-md
```

## 内容维护

- 正文内容位于 `docs/handbook/chapters/`
- 章节顺序由 `docs/handbook/handbook.config.json` 控制
- 封面图位于 `docs/handbook/assets/cover.png`
- 导出样式位于 `docs/handbook/assets/handbook.css`

## 输出文件

默认输出到：

- `dist/openclaw-handbook.html`
- `dist/openclaw-handbook.pdf`
