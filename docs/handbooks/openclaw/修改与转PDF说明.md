# OpenClaw 修改与导出说明

## 1. 当前目录结构

```text
openclaw-book/
├─ docs/
│  ├─ handbooks/
│  │  └─ openclaw/
│  │     ├─ assets/
│  │     │  ├─ cover.png
│  │     │  └─ handbook.css
│  │     ├─ chapters/
│  │     │  ├─ 00-目录.md
│  │     │  ├─ 01-初识全能小虾.md
│  │     │  ├─ 02-领养准备.md
│  │     │  ├─ 03-全线连通.md
│  │     │  ├─ 04-驯虾手册.md
│  │     │  ├─ 05-冲浪实战.md
│  │     │  ├─ 06-安全防护与急救.md
│  │     │  ├─ 07-附录与寄语.md
│  │     │  └─ 08-作者介绍.md
│  │     ├─ handbook.config.json
│  │     └─ 修改与转PDF说明.md
│  └─ references/
│     └─ pdfs/
├─ scripts/
│  ├─ render-handbook.mjs
│  └─ pdf_to_md.py
├─ dist/
├─ package.json
└─ package-lock.json
```

## 2. 平时怎么改内容

- 正文内容都在 `docs/handbooks/openclaw/chapters/` 下，按文件名前缀排序。
- 只改某一章时，直接编辑对应的 `*.md` 文件即可。
- 要调整章节顺序、增删章节、替换目录页时，修改 `docs/handbooks/openclaw/handbook.config.json` 里的 `sections` 数组。
- 封面图在 `docs/handbooks/openclaw/assets/cover.png`。
- 导出样式在 `docs/handbooks/openclaw/assets/handbook.css`。
- Markdown 文件建议统一保存为 `UTF-8` 编码。

## 3. 导出 HTML / PDF

先确认本机已安装 Node.js，并且能找到 Chrome 或 Edge。脚本会优先读取环境变量 `BROWSER_PATH`，否则自动查找常见安装路径。

查看当前有哪些手册：

```powershell
npm run handbook:list
```

导出 OpenClaw 的 HTML 和 PDF：

```powershell
npm run build:handbook -- --handbook openclaw
```

只导出 HTML：

```powershell
npm run build:handbook:html -- --handbook openclaw
```

只导出 PDF：

```powershell
npm run build:handbook:pdf -- --handbook openclaw
```

如果仓库里暂时只有这一本手册，也可以继续直接用：

```powershell
npm run build:handbook
npm run build:handbook:html
npm run build:handbook:pdf
```

为了兼容旧命令，下面这组别名也还可以继续用：

```powershell
npm run handbook
npm run handbook:html
npm run handbook:pdf
```

导出结果默认写到：

- `dist/openclaw/openclaw-handbook.html`
- `dist/openclaw/openclaw-handbook.pdf`

## 4. 把参考 PDF 转成 Markdown

项目里保留了一份无外部依赖的 PDF 转 Markdown 脚本：`scripts/pdf_to_md.py`。

单文件示例：

```powershell
python scripts/pdf_to_md.py "docs/references/pdfs/OpenClaw橙皮书-从入门到精通-v1.3.1.pdf" -o dist/converted-md
```

多文件示例：

```powershell
python scripts/pdf_to_md.py docs/references/pdfs/*.pdf -o dist/converted-md
```

如果你已经切到 PDF 所在目录，也可以直接执行：

```powershell
python ..\..\..\scripts\pdf_to_md.py *.pdf -o ..\..\..\dist\converted-md
```

## 5. 建议的维护方式

- 先修改 `chapters` 里的 Markdown，再跑一次 `npm run build:handbook:html -- --handbook openclaw` 快速检查版式。
- 确认没问题后，再执行 `npm run build:handbook -- --handbook openclaw` 生成最终 PDF。
- 如果新增了图片、附录或章节，优先同步更新 `handbook.config.json`，不要把源文件散放到根目录。