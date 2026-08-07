// 一次性工具：从 linuxdo-awesome-skills 站点 HTML 内联的 `const skills = [...]`
// 提取技能数据为标准 JSON（JS 对象字面量无法被 Python json 直接解析）。
// 用法: node apps/api/scripts/extract_linuxdo_skills.mjs <html> <out.json>
import { readFileSync, writeFileSync } from "node:fs";

const [, , htmlPath, outPath] = process.argv;
if (!htmlPath || !outPath) {
  console.error("usage: extract_linuxdo_skills.mjs <html> <out.json>");
  process.exit(1);
}
const html = readFileSync(htmlPath, "utf8");
const startIdx = html.indexOf("const skills = [");
if (startIdx === -1) {
  console.error("未找到 `const skills = [`");
  process.exit(1);
}
const slice = html.slice(startIdx + "const skills = ".length);
// 按括号深度 + 字符串感知定位数组结束的 `]`，避免误截对象内部字符串里的 ]。
let depth = 0;
let inStr = false;
let quote = "";
let end = 0;
for (let i = 0; i < slice.length; i++) {
  const c = slice[i];
  if (inStr) {
    if (c === "\\") {
      i++;
      continue;
    }
    if (c === quote) inStr = false;
    continue;
  }
  if (c === '"' || c === "'" || c === "`") {
    inStr = true;
    quote = c;
    continue;
  }
  if (c === "[") depth++;
  else if (c === "]") {
    depth--;
    if (depth === 0) {
      end = i + 1;
      break;
    }
  }
}
const arrText = slice.slice(0, end);
const skills = new Function(`return ${arrText}`)();
writeFileSync(outPath, JSON.stringify(skills, null, 2), "utf8");
console.log(`已提取 ${skills.length} 个技能 -> ${outPath}`);
if (skills[0]) console.log("示例字段:", Object.keys(skills[0]).join(", "));
