import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import process from "node:process";
import { marked } from "marked";
import { chromium } from "playwright-core";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const handbookDir = path.join(projectRoot, "docs", "handbook");
const handbookConfigPath = path.join(handbookDir, "handbook.config.json");

const browserCandidates = [
  process.env.BROWSER_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
].filter(Boolean);

const args = new Set(process.argv.slice(2));
const htmlOnly = args.has("--html-only");
const pdfOnly = args.has("--pdf-only");

marked.setOptions({
  gfm: true,
  breaks: false
});

function resolveFromConfig(configDir, value) {
  return path.resolve(configDir, value);
}

function slugify(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[`~!@#$%^&*()+=\[\]{}\\|;:'",.<>/?]+/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function stripMarkdown(value) {
  return String(value || "")
    .replace(/[*_`>#-]/g, "")
    .replace(/\[(.*?)\]\(.*?\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanBookTitle(rawTitle) {
  return stripMarkdown(rawTitle)
    .replace(/\s*\u8be6\u7ec6\u76ee\u5f55\u5927\u7eb2$/, "")
    .trim();
}

function extractFirstHeading(markdown) {
  const line = String(markdown || "")
    .split(/\r?\n/)
    .find((entry) => entry.trim().startsWith("#"));
  return line ? stripMarkdown(line.replace(/^#+\s*/, "")) : "";
}

function stripLeadingHeading(markdown) {
  return String(markdown || "").replace(
    /^(?:\uFEFF)?(?:\s*---\s*(?:\r?\n)+)?\s*#{1,6}\s+.*(?:\r?\n)+/,
    ""
  );
}

function normalizeInlineStrong(markdown) {
  return String(markdown || "").replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
}

async function readHandbookConfig() {
  const configDir = path.dirname(handbookConfigPath);
  const config = JSON.parse(await fs.readFile(handbookConfigPath, "utf8"));
  const sections = Array.isArray(config.sections) ? config.sections : [];

  if (!sections.length) {
    throw new Error(`No handbook sections configured in ${handbookConfigPath}.`);
  }

  return {
    title: config.title || "OpenClaw 手册",
    language: config.language || "zh-CN",
    cssPath: resolveFromConfig(configDir, config.stylesheet || "./assets/handbook.css"),
    coverImagePath: resolveFromConfig(configDir, config.coverImage || "./assets/cover.png"),
    outputHtmlPath: resolveFromConfig(
      configDir,
      config.output?.html || "../../dist/openclaw-handbook.html"
    ),
    outputPdfPath: resolveFromConfig(
      configDir,
      config.output?.pdf || "../../dist/openclaw-handbook.pdf"
    ),
    sections: sections.map((section, index) => {
      if (!section.file) {
        throw new Error(`Section at index ${index} is missing a file path.`);
      }

      return {
        ...section,
        filePath: resolveFromConfig(configDir, section.file)
      };
    })
  };
}

async function readBookFiles(config) {
  const docs = [];

  for (const section of config.sections) {
    const markdown = await fs.readFile(section.filePath, "utf8");
    docs.push({
      ...section,
      fileName: path.basename(section.filePath),
      markdown,
      title: section.title || extractFirstHeading(markdown)
    });
  }

  return docs;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function buildSection(doc, index) {
  const sectionSlug = slugify(`${index}-${doc.id || doc.fileName}-${doc.title}`) || `section-${index}`;
  const preparedMarkdown = normalizeInlineStrong(stripLeadingHeading(doc.markdown));
  const html = marked.parse(preparedMarkdown);
  const isToc = doc.type === "toc";
  const chapterClass = isToc ? "chapter chapter--toc toc-prose" : "chapter";
  const displayTitle = isToc ? "\u76ee\u5f55" : doc.title || `Chapter ${index}`;

  return `
    <section class="${chapterClass}" id="${sectionSlug}">
      <header class="chapter__heading">
        <h1>${escapeHtml(displayTitle)}</h1>
      </header>
      <div class="chapter__body">
        ${html}
      </div>
    </section>
  `;
}

function buildHtml({ css, docs, title, language, coverImagePath }) {
  const bookTitle = title || cleanBookTitle(docs[0]?.title) || "OpenClaw Handbook";
  const coverImageHref = pathToFileURL(coverImagePath).href;
  const renderedSections = docs.map((doc, index) => buildSection(doc, index)).join("\n");

  return `<!doctype html>
<html lang="${escapeHtml(language)}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapeHtml(bookTitle)}</title>
    <style>${css}</style>
  </head>
  <body>
    <div class="book-shell">
      <div class="page-card">
        <main class="book">
          <section class="cover" aria-label="cover">
            <img class="cover__image" src="${coverImageHref}" alt="OpenClaw cover" />
          </section>

          ${renderedSections}
        </main>
      </div>
    </div>
  </body>
</html>`;
}

async function findBrowserExecutable() {
  for (const candidate of browserCandidates) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }

  throw new Error(
    "No supported browser executable was found. Install Chrome or Edge, or set BROWSER_PATH."
  );
}

async function ensureParentDir(filePath) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
}

async function ensureCoverImage(coverImagePath) {
  await fs.access(coverImagePath);
}

async function writeHtml(html, htmlPath) {
  await ensureParentDir(htmlPath);
  await fs.writeFile(htmlPath, html, "utf8");
  return htmlPath;
}

async function writePdf(htmlPath, pdfPath) {
  await ensureParentDir(pdfPath);
  const executablePath = await findBrowserExecutable();
  const browser = await chromium.launch({
    executablePath,
    headless: true
  });

  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(htmlPath).href, {
      waitUntil: "load"
    });
    await page.waitForFunction(() => {
      const cover = document.querySelector(".cover__image");
      return Boolean(cover && cover.complete && cover.naturalWidth > 0);
    });

    await page.pdf({
      path: pdfPath,
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
      displayHeaderFooter: true,
      headerTemplate: "<div></div>",
      footerTemplate:
        "<div style=\"width:100%; padding:0 14mm; font-size:8px; color:#6f7277; font-family:'Microsoft YaHei UI',sans-serif; text-align:center;\"><span class=\"pageNumber\"></span></div>",
      margin: {
        top: "16mm",
        right: "16mm",
        bottom: "16mm",
        left: "16mm"
      }
    });

    return pdfPath;
  } finally {
    await browser.close();
  }
}

async function main() {
  const config = await readHandbookConfig();
  await ensureCoverImage(config.coverImagePath);
  const docs = await readBookFiles(config);
  const css = await fs.readFile(config.cssPath, "utf8");
  const html = buildHtml({
    css,
    docs,
    title: config.title,
    language: config.language,
    coverImagePath: config.coverImagePath
  });

  let htmlPath = config.outputHtmlPath;

  if (!pdfOnly) {
    htmlPath = await writeHtml(html, config.outputHtmlPath);
    console.log(`HTML written to ${htmlPath}`);
  } else {
    htmlPath = await writeHtml(html, config.outputHtmlPath);
  }

  if (!htmlOnly) {
    const pdfPath = await writePdf(htmlPath, config.outputPdfPath);
    console.log(`PDF written to ${pdfPath}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
