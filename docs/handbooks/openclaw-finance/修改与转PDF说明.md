# OpenClaw 财务应用实战手册维护说明

## 目录结构

```text
docs/handbooks/openclaw-finance/
├─ assets/
│  ├─ cover.png
│  └─ handbook.css
├─ chapters/
│  ├─ 00-目录.md
│  ├─ 作者介绍.md
│  ├─ chapter_01.md
│  ├─ chapter_02.md
│  ├─ ...
│  └─ chapter_10.md
├─ handbook.config.json
└─ 修改与转PDF说明.md
```

## 修改内容时看哪里

- 正文在 `docs/handbooks/openclaw-finance/chapters/`
- 封面在 `docs/handbooks/openclaw-finance/assets/cover.png`
- 章节顺序在 `docs/handbooks/openclaw-finance/handbook.config.json`
- 目录页在 `docs/handbooks/openclaw-finance/chapters/00-目录.md`
- `chapter_01.md` 到 `chapter_10.md` 是正文主章节，`作者介绍.md` 会排在封面后、目录前
- 当前封面先复用旧图，后续直接替换 `cover.png` 即可

## 导出命令

导出 HTML 和 PDF：

```powershell
npm run build:handbook -- --handbook openclaw-finance
```

只导出 HTML：

```powershell
npm run build:handbook:html -- --handbook openclaw-finance
```

只导出 PDF：

```powershell
npm run build:handbook:pdf -- --handbook openclaw-finance
```
