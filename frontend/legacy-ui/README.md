# Legacy UI archive

这里保存已经被当前资料库、控制台和工作区替代的旧界面实现。

- `snapshots/MemoryHub.legacy.tsx`：包含旧物品、叙事变化、时间线和状态账本面板。
- `snapshots/ChatWorkspace.legacy.tsx`：包含旧检查器、角色、世界书、状态、记忆、审计和运行轨迹面板。

这些文件位于 `frontend/src` 之外，不参与 TypeScript 检查和生产构建。需要恢复某个实现时，应从快照中按组件提取到当前架构，而不是直接重新启用整份历史文件。
