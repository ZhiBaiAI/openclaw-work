# 多手册目录说明

这个目录用于存放同一项目下的多本手册。渲染脚本会自动发现 `handbook.config.json`，并按目录名作为手册标识。

## 目录约定

```text
docs/handbooks/<slug>/
├─ assets/
│  ├─ cover.png
│  └─ handbook.css
├─ chapters/
│  ├─ 00-目录.md
│  └─ ...
├─ handbook.config.json
└─ 可选说明文件.md
```

其中：

- `<slug>` 是命令行里使用的手册标识，例如 `openclaw`
- `assets/` 放封面和样式
- `chapters/` 放章节 Markdown
- `handbook.config.json` 负责定义标题、语言、资源路径和章节顺序

## 命令

列出所有手册：

```powershell
npm run handbook:list
```

构建指定手册：

```powershell
npm run build:handbook -- --handbook <slug>
```

批量构建全部手册：

```powershell
npm run build:handbook:all
```

只导出 HTML 或 PDF：

```powershell
npm run build:handbook:html -- --handbook <slug>
npm run build:handbook:pdf -- --handbook <slug>
```

## 默认输出

如果 `handbook.config.json` 没有显式配置 `output`，渲染结果会默认输出到：

- `dist/<slug>/<slug>-handbook.html`
- `dist/<slug>/<slug>-handbook.pdf`

## 新增一本手册

最简单的方式是复制一个现有目录，例如：

```text
docs/handbooks/openclaw/  ->  docs/handbooks/new-book/
```

然后修改：

- `handbook.config.json` 中的标题和章节列表
- `chapters/` 内的正文
- `assets/` 下的封面和样式
