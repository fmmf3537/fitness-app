# 健身数据整合分析与指导 APP（fitness-hub）

[![CI](https://github.com/fmmf3537/fitness-app/actions/workflows/ci.yml/badge.svg)](https://github.com/fmmf3537/fitness-app/actions/workflows/ci.yml)

个人自用：融合「训记」+「佳明 Garmin」训练数据，AI 点评/建议/复盘，可安全写回训记。

## 文档导航（开发前必读，按此顺序）

1. 《健身数据整合分析APP-需求文档.md》—— 需求背景与确认结论
2. 《PRD.md》—— 产品需求文档：用户故事、数据模型、接口规格、业务规则（编码的单一事实来源）
3. 《开发计划.md》—— 三阶段任务拆解与目录骨架约定
4. 《开发提示词手册.md》—— 逐任务即贴即用的 Kimi Code 提示词（含 TDD 与敏捷纪律）

## 快速开始

```bash
# 1. 复制环境变量模板并填入真实凭据
cp .env.example .env

# 2. 在 Kimi Code 中打开本目录，先贴手册中的【P0 全局上下文】，再贴【M1】任务提示词
```

## 目录结构

```
├── backend/          # FastAPI 后端（M1 任务创建）
├── frontend/         # React 前端（M6 任务创建）
├── docs/             # 技术债清单、部署文档等（Sprint 复盘中生成）
├── 素材/             # 训记报表示例图等基准测试素材
├── PRD.md / 开发计划.md / 开发提示词手册.md / 需求文档
└── .env.example
```
