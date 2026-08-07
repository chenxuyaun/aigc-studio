// 《替身》电影剧本 docx 生成器 — 主脚本
// 内容分三个部分文件：parts/scenes1.js（场1-12）、parts/scenes2.js（场13-21）、parts/scenes3.js（场22-30）
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  PageBreak, Footer, PageNumber, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType, TableLayoutType,
} = require("docx");
const fs = require("fs");

const S1 = require("./parts/scenes1.cjs");
const S2 = require("./parts/scenes2.cjs");
const S3 = require("./parts/scenes3.cjs");
const ALL_SCENES = [...S1, ...S2, ...S3];

const FONT_CN = "SimSun";
const FONT_HEAD = "SimHei";
const FONT_YAHEI = "Microsoft YaHei";

// ── 段落工厂 ──
function h1(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 200, line: 312 },
    children: [new TextRun({ text, size: 32, bold: true, font: { eastAsia: FONT_HEAD, ascii: "Arial" }, color: "000000" })] });
}
function h2(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 160, line: 312 },
    children: [new TextRun({ text, size: 28, bold: true, font: { eastAsia: FONT_HEAD, ascii: "Arial" }, color: "000000" })] });
}
function body(text, opts = {}) {
  return new Paragraph({ spacing: { after: 120, line: 312 },
    indent: opts.noIndent ? undefined : { firstLine: 480 },
    alignment: AlignmentType.JUSTIFIED,
    children: [new TextRun({ text, size: 24, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "000000", italics: opts.italics || false, bold: opts.bold || false })] });
}
function sceneTitle(text) {
  // 场号标题：黑体加粗，居中
  return new Paragraph({ spacing: { before: 360, after: 120, line: 312 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text, size: 28, bold: true, font: { eastAsia: FONT_HEAD, ascii: "Arial" }, color: "000000" })] });
}
function sceneMeta(text) {
  // 内外景+时间：居中，楷体感（用 italic 区分）
  return new Paragraph({ spacing: { after: 160, line: 312 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text, size: 24, bold: true, italics: true, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "000000" })] });
}
function action(text) {
  return new Paragraph({ spacing: { after: 120, line: 312 }, alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: 480 },
    children: [new TextRun({ text, size: 24, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "000000" })] });
}
function dialogue(char, text) {
  // 对白：角色名加粗，内容另起行缩进
  const runs = [];
  runs.push(new TextRun({ text: char + "\uFF1A", size: 24, bold: true, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "000000" }));
  runs.push(new TextRun({ text, size: 24, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "000000" }));
  return new Paragraph({ spacing: { after: 120, line: 312 }, alignment: AlignmentType.JUSTIFIED,
    indent: { left: 720 },
    children: runs });
}
function parenthetical(text) {
  return new Paragraph({ spacing: { after: 100, line: 312 }, alignment: AlignmentType.JUSTIFIED,
    indent: { left: 960 },
    children: [new TextRun({ text: "\uFF08" + text + "\uFF09", size: 24, italics: true, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "000000" })] });
}

function sceneToParagraphs(sc) {
  const out = [sceneTitle(sc.no), sceneMeta(sc.location + "  " + sc.time)];
  for (const b of sc.blocks) {
    if (b.type === "action") out.push(action(b.text));
    else if (b.type === "dialogue") out.push(dialogue(b.char, b.text));
    else if (b.type === "paren") out.push(parenthetical(b.text));
  }
  return out;
}

// ── 封面（R1 Pure Paragraph Left）──
const coverChildren = [];
coverChildren.push(new Paragraph({ spacing: { before: 2600 } }));
coverChildren.push(new Paragraph({
  indent: { left: 1200 }, spacing: { after: 500 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2C3E50", space: 8 } },
  children: [new TextRun({ text: "S C R E E N P L A Y", size: 18, color: "2C3E50", font: { ascii: "Calibri", eastAsia: FONT_HEAD }, characterSpacing: 40 })] }));
coverChildren.push(new Paragraph({
  indent: { left: 1200 }, spacing: { after: 100, line: 2000, lineRule: "atLeast" },
  children: [new TextRun({ text: "\u66FF\u8EAB", size: 88, bold: true, color: "1A1A2E", font: { eastAsia: FONT_HEAD, ascii: "Arial" } })] }));
coverChildren.push(new Paragraph({
  indent: { left: 1200 }, spacing: { after: 600 },
  children: [new TextRun({ text: "\u300A\u66FF\u8EAB\u300B\uFF0D\uFF0D\u4E00\u5C0F\u65F6\u60AC\u7591\u7535\u5F71\u5267\u672C", size: 24, color: "3D3D5C", font: { eastAsia: FONT_YAHEI, ascii: "Arial" } })] }));
for (const line of [
  "\u7C7B\u578B\uFF1A\u60AC\u7591 / \u5FC3\u7406\u60CA\u609A / \u90FD\u5E02\u5947\u5E7B",
  "\u65F6\u957F\uFF1A\u7EA6 90 \u5206\u949F\uFF08\u53EF\u526A\u8F91\u81F3 60 \u5206\u949F\uFF09",
  "\u573A\u6B21\uFF1A30 \u573A",
  "\u4E3B\u9898\uFF1A\u6BCF\u4E2A\u4EBA\u90FD\u6709\u4E0D\u6562\u9762\u5BF9\u7684\u81EA\u5DF1",
]) {
  coverChildren.push(new Paragraph({
    indent: { left: 1400 }, spacing: { after: 80 },
    border: { left: { style: BorderStyle.SINGLE, size: 8, color: "2C3E50", space: 12 } },
    children: [new TextRun({ text: line, size: 24, color: "3D3D5C", font: { eastAsia: FONT_YAHEI, ascii: "Arial" } })] }));
}
coverChildren.push(new Paragraph({ spacing: { before: 2800 } }));
coverChildren.push(new Paragraph({
  indent: { left: 1200, right: 800 },
  border: { top: { style: BorderStyle.SINGLE, size: 2, color: "2C3E50", space: 8 } },
  spacing: { before: 200 },
  children: [new TextRun({ text: "AI \u5267\u672C\u5DE5\u4F5C\u5BA4", size: 16, color: "7A7A9A", font: { ascii: "Arial" } })] }));

// ── 角色表 ──
function charTable() {
  const rows = [];
  rows.push(new TableRow({ tableHeader: true, cantSplit: true, children: [
    new TableCell({ margins: { top: 80, bottom: 80, left: 120, right: 120 }, shading: { type: ShadingType.CLEAR, fill: "E8ECF1" },
      children: [new Paragraph({ children: [new TextRun({ text: "\u89D2\u8272", bold: true, size: 21, font: { eastAsia: FONT_HEAD, ascii: "Arial" } })] })] }),
    new TableCell({ margins: { top: 80, bottom: 80, left: 120, right: 120 }, shading: { type: ShadingType.CLEAR, fill: "E8ECF1" },
      children: [new Paragraph({ children: [new TextRun({ text: "\u8BBE\u5B9A", bold: true, size: 21, font: { eastAsia: FONT_HEAD, ascii: "Arial" } })] })] }),
  ] }));
  for (const [n, d] of [
    ["\u6797\u9ED8", "36 \u5C81\uFF0C\u60AC\u7591\u5C0F\u8BF4\u4F5C\u5BB6\u3002\u4E09\u5E74\u524D\u51ED\u300A\u65E0\u58F0\u8BC1\u8BCD\u300B\u6210\u540D\u540E\u6C5F\u90CE\u624D\u5C3D\uFF0C\u5199\u4E0D\u51FA\u7ED3\u5C40\uFF0C\u9169\u9152\u3002"],
    ["\u59DC\u84C9", "30 \u5C81\uFF0C\u5E02\u5211\u652F\u652F\u961F\u5211\u8B66\u3002\u51B7\u9759\u5BE1\u8A00\u300212 \u5E74\u524D\u6BCD\u4EB2\u5931\u8E2A\uFF0C\u51B7\u6848\u672A\u7834\u3002"],
    ["\u9648\u5F8B\u5E08", "48 \u5C81\uFF0C\u6797\u9ED8\u7684\u4EE3\u7406\u5F8B\u5E08\u517C\u552F\u4E00\u670B\u53CB\uFF0C\u7B2C\u4E00\u4E2A\u6B7B\u8005\u3002"],
    ["\u5F71\u5B50", "\u4E66\u4E2D\u53CD\u6D3E\uFF0C\u65E0\u5177\u4F53\u5F62\u8C61\u3002\u5728\u6797\u9ED8\u68A6\u91CC\u4EE5\u7A7F\u98CE\u8863\u3001\u65E0\u8138\u7684\u8F6E\u5ED3\u51FA\u73B0\u3002"],
  ]) {
    rows.push(new TableRow({ cantSplit: true, children: [
      new TableCell({ margins: { top: 60, bottom: 60, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: n, bold: true, size: 21, font: { eastAsia: FONT_CN, ascii: "Times New Roman" } })] })] }),
      new TableCell({ margins: { top: 60, bottom: 60, left: 120, right: 120 }, children: [new Paragraph({ spacing: { line: 288 }, children: [new TextRun({ text: d, size: 21, font: { eastAsia: FONT_CN, ascii: "Times New Roman" } })] })] }),
    ] }));
  }
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: { top: { style: BorderStyle.SINGLE, size: 2, color: "9AA6B2" }, bottom: { style: BorderStyle.SINGLE, size: 2, color: "9AA6B2" },
      left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: "D0D0D0" }, insideVertical: { style: BorderStyle.NONE } },
    rows,
  });
}

// ── 分场表 ──
function sceneTable() {
  const rows = [];
  rows.push(new TableRow({ tableHeader: true, cantSplit: true, children: [
    ["\u573A", 720], ["\u5E55", 540], ["\u65F6\u95F4", 1080], ["\u5185\u5BB9", null],
  ].map(([t, w]) => new TableCell({ margins: { top: 60, bottom: 60, left: 100, right: 100 }, shading: { type: ShadingType.CLEAR, fill: "E8ECF1" },
    children: [new Paragraph({ children: [new TextRun({ text: t, bold: true, size: 20, font: { eastAsia: FONT_HEAD, ascii: "Arial" } })] })] })) }));
  const data = [
    ["1", "\u4E00", "0-2m", "\u6DF1\u591C\u4E66\u623F\uFF0C\u6797\u9ED8\u5199\u5B8C\u7B2C 13 \u7AE0\uFF0C\u5220\u6389\u300C\u9648\u5F8B\u5E08\u4E4B\u6B7B\u300D"],
    ["2", "\u4E00", "2-5m", "\u6B21\u65E5\u65B0\u95FB\uFF1A\u5F8B\u5E08\u5760\u697C\u8EAB\u4EA1\uFF0C\u7EC6\u8282\u4E0E\u4ED6\u5220\u6389\u7684\u7A3F\u5B50\u9010\u5B57\u5408\u3002"],
    ["3", "\u4E00", "5-8m", "\u6797\u9ED8\u7FFB\u65E7\u7A3F\uFF0C\u53D1\u73B0\u6B64\u7AE0\u8282\u65E5\u671F\u662F\u4E09\u4E2A\u6708\u524D\u3002"],
    ["4", "\u4E00", "8-11m", "\u59DC\u84C9\u4E0A\u95E8\u8C03\u67E5\uFF0C\u6797\u9ED8\u9690\u779E\uFF1B\u5979\u6CE8\u610F\u5230\u6253\u5B57\u673A\u3002"],
    ["5", "\u4E00", "11-14m", "\u6797\u9ED8\u68A6\u89C1\u300C\u5F71\u5B50\u300D\uFF0C\u5F71\u5B50\u8BF4\u300C\u4F60\u8FD8\u6CA1\u5199\u5B8C\u300D\u3002"],
    ["6", "\u4E00", "14-17m", "\u6797\u9ED8\u8BD5\u5199\u90BB\u5C45\u5BB6\u7684\u72D7\uFF0C\u72D7\u6D3B\u4E0B\u6765\uFF1B\u4ED6\u7B2C\u4E00\u6B21\u786E\u8BA4\u300C\u7B14\u529B\u300D\u3002"],
    ["7", "\u4E00", "17-19m", "\u9648\u5F8B\u5E08\u5893\u524D\uFF0C\u5893\u7891\u4E0A\u7684\u6B7B\u4EA1\u65E5\u671F\u88AB\u6539\u5199\u3002"],
    ["8", "\u4E8C", "19-22m", "\u59DC\u84C9\u590D\u67E5\u6863\u6848\uFF1A\u4E09\u4E2A\u6B7B\u8005\u66FE\u540C\u65F6\u51FA\u73B0\u5728\u7B7E\u552E\u4F1A\u3002"],
    ["9", "\u4E8C", "22-25m", "\u6797\u9ED8\u8BD5\u5199\u300C\u6551\u4EBA\u300D\uFF0C\u5F53\u665A\u5931\u53BB\u4E00\u6BB5\u8BB0\u5FC6\u3002"],
    ["10", "\u4E8C", "25-28m", "\u4EE3\u4EF7\u663E\u73B0\uFF1A\u4ED6\u5FD8\u8BB0\u6BCD\u4EB2\u7684\u8138\uFF08\u66F8\u4E2D\u8BBE\u5B9A\uFF09\u3002"],
    ["11", "\u4E8C", "28-31m", "\u59DC\u84C9\u6DF1\u591C\u518D\u6765\uFF0C\u4E24\u4EBA\u7B2C\u4E00\u6B21\u4EA4\u5E95\u3002"],
    ["12", "\u4E8C", "31-34m", "\u6848\u5377\u91CC\u6BCD\u4EB2\u7684\u7167\u7247\u88AB\u300C\u4E66\u9875\u300D\u65B9\u5F0F\u64E6\u53BB\u534A\u5F20\u8138\u3002"],
    ["13", "\u4E8C", "34-37m", "\u6797\u9ED8\u627E\u5230\u65E7\u51FA\u7248\u793E\uFF0C\u8001\u677F\u5A18\u8BB0\u5F97\u300A\u5F71\u5B50\u300B\u7684\u7F16\u8F91\u3002"],
    ["14", "\u4E8C", "37-40m", "\u7F16\u8F91\u5DF2\u6B7B\u5341\u5E74\u2014\u2014\u6B7B\u4E8E\u300C\u4E66\u4E2D\u89D2\u8272\u300D\u540C\u6B3E\u6B7B\u6CD5\u3002"],
    ["15", "\u4E8C", "40-43m", "\u65E7\u4ED3\u5E93\u627E\u5230\u300A\u5F71\u5B50\u300B\u7B2C 0 \u7AE0\u6B8B\u7A3F\u3002"],
    ["16", "\u4E09", "43-46m", "\u6B8B\u7A3F\u663E\u5F71\uFF1A24 \u5C81\u7B14\u8FF9\u300C\u6211\u4F1A\u4EB2\u624B\u6740\u6B7B\u4ED6\u300D\u3002"],
    ["17", "\u4E09", "46-49m", "\u59DC\u84C9\u67E5\u5230\u8F66\u7978\u5906\u5931\u5386\uFF0C\u62A5\u8B66\u5F55\u97F3\u300C\u6709\u4EBA\u8981\u6740\u6211\u300D\u3002"],
    ["18", "\u4E09", "49-52m", "\u5F71\u5B50\u68A6\u91CC\u644A\u724C\uFF1A\u6211\u662F\u4F60 12 \u5E74\u524D\u70E7\u6389\u7684\u7ED3\u5C40\u3002"],
    ["19", "\u4E09", "52-55m", "\u6797\u9ED8\u5199\u300A\u66FF\u8EAB\u300B\u7EC8\u7AE0\uFF1A\u8BA9\u5F71\u5B50\u53D6\u4EE3\u81EA\u5DF1\u3002"],
    ["20", "\u4E09", "55-58m", "\u4EA4\u6362\u53D1\u751F\u3002\u5F71\u5B50\u7A7F\u7740\u6797\u9ED8\u7684\u98CE\u8863\u9192\u6765\u3002"],
    ["21", "\u4E09", "58-60m", "\u7B7E\u552E\u4F1A\uFF0C\u7B7E\u540D\u7B14\u8FF9\u6539\u53D8\uFF0C\u59DC\u84C9\u53D1\u73B0\u3002"],
    ["22", "\u5C3E", "60-63m", "\u59DC\u84C9\u5728\u6BCD\u4EB2\u9057\u7269\u7BB1\u627E\u5230\u592A\u9633\u82B1\u7167\u7247\u3002"],
    ["23", "\u5C3E", "63-66m", "\u5B64\u513F\u9662\u5E9F\u589F\u627E\u5230\u300A\u5F71\u5B50\u00B7\u7B2C\u4E00\u7A3F\u300B\uFF0C\u9644\u5730\u4E0B\u4E8C\u5C42\u771F\u76F8\u3002"],
    ["24", "\u5C3E", "66-69m", "\u6797\u9ED8\u4E66\u623F\u7684\u6253\u5B57\u673A\u7559\u4E0B\u6307\u793A\uFF1A\u53BB\u8001\u623F\u5B50\u9601\u697C\u3002"],
    ["25", "\u5C3E", "69-72m", "\u9601\u697C\u627E\u5230 1998 \u5E74\u7B14\u8BB0\u672C\uFF0C0331 \u53F7\u5B64\u513F\u7684\u771F\u76F8\u3002"],
    ["26", "\u5C3E", "72-75m", "\u4E66\u4E2D\u4E16\u754C\uFF1A\u6797\u9ED8\u6210\u4E86\u5F71\u5B50\uFF0C\u4ED6\u4E0E\u59DC\u84C9\u5728\u7EB8\u4E0A\u5BF9\u8BDD\u3002"],
    ["27", "\u5C3E", "75-78m", "\u59DC\u84C9\u60F3\u901A\u771F\u76F8\uFF1A\u6797\u9ED8\u4ECE\u6765\u4E0D\u662F\u5199\u6B7B\u522B\u4EBA\u7684\u4EBA\u3002"],
    ["28", "\u5C3E", "78-81m", "\u59DC\u84C9\u7528\u94A2\u7B14\u5199\u4E0B\u300C\u4ED6\u6D3B\u7740\u300D\uFF0C\u6253\u5B57\u673A\u5410\u51FA\u300C\u8C22\u8C22\u300D\u3002"],
    ["29", "\u5C3E", "81-84m", "\u7B7E\u552E\u4F1A\uFF0C\u5F71\u5B50\u7684\u7B7E\u540D\u51FA\u73B0\u6797\u9ED8\u7684\u505C\u987F\u4E60\u60EF\u3002"],
    ["30", "\u5C3E", "84-87m", "\u6797\u9ED8\u56DE\u6765\u3002\u592A\u9633\u82B1\u3002\u65E0\u540D\u7684\u4E66\u6D6E\u73B0\u300C\u5F71\u5B50\u300D\u3002"],
  ];
  for (const [no, act, t, content] of data) {
    rows.push(new TableRow({ cantSplit: true, children: [
      new TableCell({ margins: { top: 50, bottom: 50, left: 100, right: 100 }, children: [new Paragraph({ children: [new TextRun({ text: no, size: 20, font: { eastAsia: FONT_CN, ascii: "Times New Roman" } })] })] }),
      new TableCell({ margins: { top: 50, bottom: 50, left: 100, right: 100 }, children: [new Paragraph({ children: [new TextRun({ text: act, size: 20, font: { eastAsia: FONT_CN, ascii: "Times New Roman" } })] })] }),
      new TableCell({ margins: { top: 50, bottom: 50, left: 100, right: 100 }, children: [new Paragraph({ children: [new TextRun({ text: t, size: 20, font: { eastAsia: FONT_CN, ascii: "Times New Roman" } })] })] }),
      new TableCell({ margins: { top: 50, bottom: 50, left: 100, right: 100 }, children: [new Paragraph({ spacing: { line: 288 }, children: [new TextRun({ text: content, size: 20, font: { eastAsia: FONT_CN, ascii: "Times New Roman" } })] })] }),
    ] }));
  }
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: { top: { style: BorderStyle.SINGLE, size: 2, color: "9AA6B2" }, bottom: { style: BorderStyle.SINGLE, size: 2, color: "9AA6B2" },
      left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: "D0D0D0" }, insideVertical: { style: BorderStyle.NONE } },
    rows,
  });
}

// ── 文档正文 children ──
const bodyChildren = [];
bodyChildren.push(h1("\u300A\u66FF\u8EAB\u300B\u60AC\u7591\u7535\u5F71\u5267\u672C"));

bodyChildren.push(h2("\u4E00\u3001\u5267\u672C\u4FE1\u606F"));
bodyChildren.push(body("\u7C7B\u578B\uFF1A\u60AC\u7591 / \u5FC3\u7406\u60CA\u609A / \u90FD\u5E02\u5947\u5E7B", { noIndent: true }));
bodyChildren.push(body("\u65F6\u957F\uFF1A\u7EA6 90 \u5206\u949F\uFF08\u542B\u5C3E\u58F0\uFF0C\u53EF\u526A\u8F91\u81F3 60 \u5206\u949F\uFF09", { noIndent: true }));
bodyChildren.push(body("\u573A\u6B21\uFF1A30 \u573A", { noIndent: true }));
bodyChildren.push(body("\u4E00\u53E5\u8BDD\u6982\u62EC\uFF1A\u6C5F\u90CE\u624D\u5C3D\u7684\u60AC\u7591\u4F5C\u5BB6\u6797\u9ED8\u53D1\u73B0\uFF0C\u81EA\u5DF1\u7B14\u4E0B\u7684\u4EBA\u7269\u6B63\u5728\u73B0\u5B9E\u4E2D\u4E00\u4E2A\u4E2A\u6B7B\u53BB\u3001\u6B7B\u6CD5\u4E0E\u4ED6\u5199\u7684\u4E00\u6A21\u4E00\u6837\u2014\u2014\u800C\u6700\u65B0\u4E00\u7AE0\u7684\u53CD\u6D3E\uFF0C\u662F\u4ED6\u81EA\u5DF1\u3002", { noIndent: true }));

bodyChildren.push(h2("\u4E8C\u3001\u6838\u5FC3\u8BBE\u5B9A\uFF08\u7B14\u529B\u89C4\u5219\uFF09"));
for (const t of [
  "1. \u6797\u9ED8\u5199\u4E0B\u7684\u6B7B\u4EA1\u63CF\u8FF0\uFF0C\u4F1A\u5728 24 \u5C0F\u65F6\u5185\u4E8E\u73B0\u5B9E\u4E2D\u5E94\u9A8C\uFF0C\u6B7B\u6CD5\u9010\u5B57\u5408\u3002",
  "2. \u4ED6\u5199\u6551\u4EBA\u4E5F\u53EF\u4EE5\u751F\u6548\uFF0C\u4F46\u6BCF\u6539\u5199\u4E00\u6B21\uFF0C\u73B0\u5B9E\u4F1A\u8865\u507F\u6027\u5730\u593A\u8D70\u53E6\u4E00\u6837\u4E1C\u897F\uFF08\u7075\u611F\u3001\u8BB0\u5FC6\u3001\u6700\u540E\u662F\u81EA\u5DF1\uFF09\u3002",
  "3. 12 \u5E74\u524D\u4ED6\u70E7\u6389\u5904\u5973\u4F5C\u300A\u5F71\u5B50\u300B\u2014\u2014\u90A3\u672C\u4E66\u7684\u7ED3\u5C40\uFF0C\u662F\u4ED6\u7ED9\u81EA\u5DF1\u5199\u7684\u6B7B\u4EA1\u3002\u70E7\u6389\u624B\u7A3F\u7684\u540C\u65F6\uFF0C\u4ED6\u5931\u53BB\u4E86\u90A3\u5E74\u7684\u5168\u90E8\u8BB0\u5FC6\u3002",
  "4. \u88AB\u300C\u5F71\u5B50\u300D\u6740\u6B7B\u7684\u73B0\u5B9E\u4EBA\u7269\uFF0C\u4F1A\u4ECE\u6240\u6709\u4EBA\u7684\u8BB0\u5FC6\u4E2D\u6D88\u5931\uFF08\u88AB\u4E16\u754C\u6539\u5199\uFF09\u3002",
]) bodyChildren.push(body(t));

bodyChildren.push(h2("\u4E09\u3001\u89D2\u8272\u8868"));
bodyChildren.push(charTable());

bodyChildren.push(h2("\u56DB\u3001\u6545\u4E8B\u6982\u62EC"));
bodyChildren.push(body("\u6C5F\u90CE\u624D\u5C3D\u7684\u60AC\u7591\u4F5C\u5BB6\u6797\u9ED8\uFF0C\u5728\u6DF1\u591C\u5199\u5B8C\u65B0\u4E66\u7B2C 13 \u7AE0\u540E\u5220\u6389\u4E86\u300C\u9648\u5F8B\u5E08\u4E4B\u6B7B\u300D\u3002\u6B21\u65E5\uFF0C\u4ED6\u7684\u4EE3\u7406\u5F8B\u5E08\u9648\u6B63\u660E\u771F\u7684\u4ECE\u5199\u5B57\u697C\u5760\u4E0B\u8EAB\u4EA1\u2014\u2014\u6B7B\u6CD5\u4E0E\u4ED6\u5220\u6389\u7684\u7A3F\u5B50\u9010\u5B57\u76F8\u540C\uFF0C\u800C\u90A3\u7AE0\u7A3F\u5B50\u7684\u65E5\u671F\u662F\u4E09\u4E2A\u6708\u524D\u3002\u5211\u8B66\u59DC\u84C9\u8C03\u67E5\u8FDE\u73AF\u6B7B\u4EA1\u6848\uFF0C\u53D1\u73B0\u6240\u6709\u6B7B\u8005\u90FD\u66FE\u51FA\u73B0\u5728\u6797\u9ED8\u7684\u7B7E\u552E\u4F1A\u4E0A\u3002"));
bodyChildren.push(body("\u6797\u9ED8\u8BD5\u56FE\u5199\u300C\u6551\u4EBA\u300D\uFF0C\u5374\u4ED8\u51FA\u5931\u53BB\u8BB0\u5FC6\u7684\u4EE3\u4EF7\uFF1B\u968F\u7740\u8FFD\u67E5\u6DF1\u5165\uFF0C\u4ED6\u627E\u5230 12 \u5E74\u524D\u70E7\u6389\u7684\u5904\u5973\u4F5C\u300A\u5F71\u5B50\u300B\u6B8B\u7A3F\u2014\u2014\u4ED6\u81EA\u5DF1\u624D\u662F\u66F8\u91CC\u88AB\u64E6\u9664\u7684\u89D2\u8272\uFF0C\u800C\u300C\u5F71\u5B50\u300D\u6B63\u5728\u501F\u4ED6\u7684\u7B14\u5B8C\u6210 12 \u5E74\u524D\u7684\u7ED3\u5C40\u3002\u6700\u7EC8\uFF0C\u6797\u9ED8\u5199\u4E0B\u300A\u66FF\u8EAB\u300B\u7EC8\u7AE0\uFF0C\u8BA9\u5F71\u5B50\u8D70\u8FDB\u73B0\u5B9E\u3001\u81EA\u5DF1\u8D70\u8FDB\u66F8\u9875\uFF1B\u59DC\u84C9\u7528\u4E00\u652F\u53D1\u70EB\u7684\u94A2\u7B14\uFF0C\u4E3A\u4ED6\u5199\u4E0B\u65B0\u7684\u7ED3\u5C40\u3002"));

bodyChildren.push(h2("\u4E94\u3001\u5206\u573A\u8868"));
bodyChildren.push(sceneTable());

// 正文分场
bodyChildren.push(h2("\u516D\u3001\u6B63\u6587\uFF08\u5168 30 \u573A\uFF09"));
for (const sc of ALL_SCENES) {
  bodyChildren.push(...sceneToParagraphs(sc));
}

// ── 文档 ──
const doc = new Document({
  styles: { default: { document: { run: { font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, size: 24 } } } },
  sections: [
    // 封面 section（无页脚）
    { properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 0, bottom: 0, left: 0, right: 0 } } },
      children: [new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, layout: TableLayoutType.FIXED,
        borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE }, insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE } },
        rows: [new TableRow({ height: { value: 16838, rule: "exact" }, children: [new TableCell({ shading: { type: ShadingType.CLEAR, fill: "FAF7F2" }, borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } }, children: coverChildren })] })] })] },
    // 正文 section（页码从 1 开始）
    { properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1701, right: 1417 }, pageNumbers: { start: 1, formatType: "decimal" } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
        new TextRun({ text: "\u300A\u66FF\u8EAB\u300B  \u00B7  \u7B2C ", size: 18, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "666666" }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18, font: { ascii: "Times New Roman" }, color: "666666" }),
        new TextRun({ text: " \u9875", size: 18, font: { eastAsia: FONT_CN, ascii: "Times New Roman" }, color: "666666" }),
      ] })] }) },
      children: bodyChildren },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("替身-完整剧本.docx", buf);
  console.log("OK: 替身-完整剧本.docx (" + buf.length + " bytes, " + ALL_SCENES.length + " scenes)");
});
