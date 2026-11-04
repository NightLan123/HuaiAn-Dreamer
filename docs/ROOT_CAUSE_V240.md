# 2.2.3 启动故障与根因边界

确定的启动缺陷：2.2.2 HTML 在 dynamicBoundaryDialog / brmCalibrationDialog 之前加载普通 app.js；脚本顶层立即访问表单，节点尚未解析，导致初始化中断。这与截图中持续“正在连接本地程序”一致。H1 将脚本移至最后并 defer，本版已合并。旧版 HTML 顺序断言失败，新版通过。

此前的结构 DOM 测试先构建整棵树，再运行脚本，因此不能发现这个解析先后问题。新增检查直接扫描实际交付 HTML。21 场景联调继续检查完整 app.js、本机 HTTP、Cookie、错误恢复和表单，但仍不是渲染浏览器。

独立后端故障仍可能存在：若新版脚本正确加载而 /api/state 返回错误，应以该请求的 request_id、method/path/status 和脱敏堆栈定位，不能把所有白页都归为 H1。原始生产库和首个故障 HTTP body 没有取得。

其他本轮确认缺陷与修复详见 VERSION_AUDIT_20261028.md。2.2.2 之前的诊断与未知归因保留在 ROOT_CAUSE_V222.md，不能将其历史“待定位”当作本次已经完成的实机验收。
