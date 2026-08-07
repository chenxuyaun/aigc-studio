import type { NodeTypes } from "@xyflow/react";
import { SkillNode } from "./SkillNode";
import { PromptNode } from "./PromptNode";
import { AgentNode } from "./AgentNode";

export const nodeTypes: NodeTypes = {
  skill: SkillNode,
  prompt: PromptNode,
  agent: AgentNode,
};

export { SkillNode, PromptNode, AgentNode };
