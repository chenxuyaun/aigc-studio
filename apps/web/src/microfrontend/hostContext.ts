import { createContext, useContext } from "react";

import type { AigcStudioHostProps } from "@aigc/shared-types";

/**
 * 宿主上下文：Standalone 模式为空对象，Remote 模式携带主系统下发的
 * token / 主题 / 用户 / 导航回调等。业务代码通过 useHost() 读取，
 * 不得直接访问 window 上的全局变量。
 */
const HostContext = createContext<AigcStudioHostProps>({});

export const HostProvider = HostContext.Provider;

export function useHost(): AigcStudioHostProps {
  return useContext(HostContext);
}
