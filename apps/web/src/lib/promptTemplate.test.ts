import { describe, expect, it } from "vitest";

import { applyTemplateValues, parseTemplateVariables } from "@/lib/promptTemplate";

describe("parseTemplateVariables", () => {
  it("解析标准 name+default 语法", () => {
    const vars = parseTemplateVariables(
      '一张以 {argument name="theme" default="火车摄影"} 为主题的游戏截图',
    );
    expect(vars).toEqual([{ name: "theme", defaultValue: "火车摄影" }]);
  });

  it("解析 JSON 转义语法（反斜杠引号形式）", () => {
    const vars = parseTemplateVariables(
      '{argument name=\\"headline text\\" default=\\"大语言模型\\"} 标题',
    );
    expect(vars).toEqual([{ name: "headline text", defaultValue: "大语言模型" }]);
  });

  it("解析 default 内嵌转义引号的复杂值", () => {
    const vars = parseTemplateVariables(
      '{argument name="closing" default="变成\\"超会聊天\\"的小助手"}',
    );
    expect(vars).toEqual([{ name: "closing", defaultValue: '变成"超会聊天"的小助手' }]);
  });

  it("多个变量按顺序返回并去重", () => {
    const vars = parseTemplateVariables(
      '{argument name="a" default="1"} {argument name="b" default="2"} {argument name="a" default="3"}',
    );
    expect(vars.map((v) => v.name)).toEqual(["a", "b"]);
  });

  it("无 default 时返回空默认值", () => {
    const vars = parseTemplateVariables('{argument name="only"}');
    expect(vars).toEqual([{ name: "only", defaultValue: "" }]);
  });

  it("无模板时返回空数组", () => {
    expect(parseTemplateVariables("普通提示词 {not_argument}")).toEqual([]);
  });
});

describe("applyTemplateValues", () => {
  it("替换变量值为填写内容", () => {
    const out = applyTemplateValues(
      '一张以 {argument name="theme" default="火车摄影"} 为主题的游戏截图',
      { theme: "太空站" },
    );
    expect(out).toBe("一张以 太空站 为主题的游戏截图");
  });

  it("未提供的变量保留原块", () => {
    const out = applyTemplateValues(
      '{argument name="a" default="1"} {argument name="b" default="2"}',
      { a: "x" },
    );
    expect(out).toBe("x {argument name=\"b\" default=\"2\"}");
  });

  it("清理转义语法中的残留引号", () => {
    const out = applyTemplateValues(
      '{argument name=\\"title\\" default=\\"出师表\\"} 原文',
      { title: "岳阳楼记" },
    );
    expect(out).toBe("岳阳楼记 原文");
  });

  it("空值也替换（用户清空输入框）", () => {
    const out = applyTemplateValues('{argument name="a" default="1"}', { a: "" });
    expect(out).toBe("");
  });
});
