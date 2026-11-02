# SDK实测姿态显示与编辑限位分离

状态：本地修复，未部署。

## 现场证据

GPT内置浏览器显示SDK Connected / fresh，实际J2为-12.21°，模型编辑下限为-12°。旧receiveLive调用目标validate，抛错导致六轴/夹爪/法兰输入都不更新，界面显示Measured pose cannot be represented by this model。随后J2实测变为7.38°，六轴输入与实际反馈一致，真实Three.js模型自动跟随；全程未发送运动，也未重新初始化SDK。

## 修复与边界

- robot-viewer.js新增setMeasuredJointAngles，严格要求六个有限数值；仅此次显示时暂时绕过URDF编辑限位，finally恢复。测量角度不夹紧、不伪造。setJointAngles、jointLimits和运动校验不变。
- simulation-controller.js将receiveLive与目标validate分开；仍要求默认跟随开启，非法数据拒绝；无网络/SDK调用。
- workspace-session.js更新数值框到真实角度；超出编辑范围的滑条暂时禁用并解释，原min/max不扩大。人工编辑停止跟随，全部目标合法后才应用草稿，避免连带夹紧其他关节。手动恢复同步再采用最新鲜实测。
- i18n-cloud-catalog.js同步中英文提示。现有fresh/connected/hardware及SDK连接门禁不变；过期/断线保留最后姿态。

数据流仍为只读store→workspace→simulation→ArmModel→Three.js与输入框。四件浏览器源码；无API/数据库迁移/权限/Ubuntu/网络/租约/依赖变化，启动命令沿用现有cloud工作台。

## 验证

78项Node测试通过，覆盖现代/经典、观察员/管理员、手动草稿、失联/恢复/无效数据、数值单位、以及J2=-12.21°原值显示与目标仍拒绝；真实ArmModel方法测试URDF临时ignoreLimits在正常和异常路径恢复。测试替身验证越界路径，不冒充已经上线的真实SDK越界验收。

范围内线上真实同步已经观察；越界显示修复尚待固定候选审批和部署。不会为复现而运动真机；如没有自然出现的越界反馈，只验收已有被动反馈并保留该验收限制。长期SDK稳定性、后台隐藏释放等独立问题未在此包修改。
