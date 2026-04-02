# Handbook Workspace

这是一个用于维护和导出多个 Markdown 手册的工作区。

每本手册都放在独立目录下，通过同一套 Node.js 脚本渲染为 HTML，并可继续导出为 PDF。当前仓库内已内置 `openclaw` 作为第一本示例手册，后续可以继续新增更多手册而不需要再改脚本。

## 目录结构

```text
openclaw-book/
├─ docs/
│  ├─ handbooks/
│  │  ├─ README.md
│  │  └─ openclaw/
│  │     ├─ assets/
│  │     ├─ chapters/
│  │     ├─ handbook.config.json
│  │     └─ 修改与转PDF说明.md
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

查看当前已注册的手册：

```powershell
npm run handbook:list
```

导出 HTML 和 PDF：

```powershell
npm run build:handbook
```

如果仓库里有多本手册，指定某一本：

```powershell
npm run build:handbook -- --handbook openclaw
```

批量导出全部手册：

```powershell
npm run build:handbook:all
```

只导出 HTML：

```powershell
npm run build:handbook:html
```

多手册场景下只导出某一本 HTML：

```powershell
npm run build:handbook:html -- --handbook openclaw
```

只导出 PDF：

```powershell
npm run build:handbook:pdf
```

兼容别名命令：

```powershell
npm run handbook
npm run handbook:all
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

- 每本手册放在 `docs/handbooks/<slug>/`
- 正文内容位于 `docs/handbooks/<slug>/chapters/`
- 章节顺序由 `docs/handbooks/<slug>/handbook.config.json` 控制
- 封面图位于 `docs/handbooks/<slug>/assets/cover.png`
- 导出样式位于 `docs/handbooks/<slug>/assets/handbook.css`
- 如果当前只有一本手册，`npm run build:handbook` 会直接构建它；如果后续存在多本手册，请显式传入 `--handbook <slug>` 或使用 `build:handbook:all`

新增一本手册时，直接复制一个现有目录即可，例如：

```text
docs/handbooks/new-book/
├─ assets/
├─ chapters/
└─ handbook.config.json
```

## 输出文件

默认输出到 `dist/<slug>/`：

- `dist/openclaw/openclaw-handbook.html`
- `dist/openclaw/openclaw-handbook.pdf`
