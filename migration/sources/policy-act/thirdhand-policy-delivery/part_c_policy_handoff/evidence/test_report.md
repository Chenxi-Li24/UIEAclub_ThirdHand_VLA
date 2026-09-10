# PART C Policy 测试报告

- **日期**: 2026-08-17
- **代码版本**: 未纳入 git 仓库（branch/commit 待定，交付时如实标注，不伪造）
- **测试环境**: 本地 Windows Python 3.14.6 + jsonschema 4.26.0（完整测试）；部署机 Ubuntu Python 3.8.10（192.168.58.68，可跑不含 numpy 依赖的 25 个用例）
- **CUDA/PyTorch/LeRobot**: 未安装（`lerobot_act` 真推理不在本次验证范围，如实标注）

## 单元测试

```
命令: python -m pytest tests/ -q
结果: 27 passed, 0 failed
```

## Smoke 测试

```
命令: python3 client/dry_run_chain.py
结果: 全链路 dry-run 回放通过
      traceId 一致 / replyTo 链连续（11 条消息）/ Policy 环节与官方 demo_flow 的
      msg-005→msg-006 逐字段一致 / schema.json 校验通过
日志: evidence/smoke_test.log
```

## PART C 第 6 节要求的 11 项测试对照

| # | 要求 | 对应测试 | 结果 |
|---|---|---|---|
| 1 | 合法固定路线请求返回 schema-valid ready 计划 | `test_fixed_baseline_returns_valid_result` | ✅ |
| 2 | ACT 合法请求返回 schema-valid act_chunk | `test_fake_act_returns_valid_result` | ✅ |
| 3 | 未授权目标被拒绝 | `test_unauthorized_target_rejected` | ✅ |
| 4 | targetId/frameId/maskRef 缺失被拒绝 | `test_missing_target_field_rejected`（3 参数化） | ✅ |
| 5 | robotStateRef 缺失被拒绝 | `test_missing_robot_state_ref_rejected` | ✅ |
| 6 | action space 不兼容被拒绝 | `test_incompatible_action_space_returns_error` | ✅ |
| 7 | 不支持的 policy kind 被拒绝 | `test_no_allowed_kind_returns_error` | ✅ |
| 8 | checkpoint 缺失被拒绝 | `test_lerobot_act_without_checkpoint_rejected` | ✅ |
| 9 | act_chunk 所需 adapter 未注册 fail closed | `test_act_chunk_falls_back_to_fixed_baseline_when_adapter_unavailable`、`test_act_chunk_fails_closed_when_adapter_unavailable_and_fixed_not_allowed` | ✅ |
| 10 | 内部异常返回明确失败，不产生可执行计划 | `test_internal_policy_error_returns_service_error_without_plan` | ✅ |
| 11 | 全部样例通过 JSON 解析和 schema 校验 | `examples/` 5 个文件（见下） | ✅ |

## 样例校验

```
examples/policy_action_request_ready.json              JSON 可解析、无重复 key、schema 0 错误
examples/policy_action_result_ready.json               JSON 可解析、无重复 key、schema 0 错误
examples/policy_action_request_invalid_target.json     JSON 可解析、无重复 key（authorized=false 为故意构造的非法目标，schema 拒绝该值正是预期证据）
examples/policy_action_result_failure.json             JSON 可解析、无重复 key、schema 0 错误（service.error, stage=policy）
examples/policy_action_result_timeout_or_error.json    JSON 可解析、无重复 key、schema 0 错误（service.error, stage=policy）
```

## 声明

本报告只证明 **simulate / dry-run 链路** 的正确性。**不包含任何真实机器人运动或真实抓取验证**；真机执行需按契约 L0-L3 逐级验收，由 Robot 模块和现场安全负责人执行。
