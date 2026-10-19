# xzxg-shop Python Web Refactor

本项目是 [LYP-leo/xzxg-shop](https://github.com/LYP-leo/xzxg-shop) 的 Python 后端重构版本，当前只保留 Web 版本。

原项目名称是“小猪小狗 AI 导购系统”，定位是一个结合电商交易和 AI 导购能力的购物系统。本仓库保留原项目的 React Web 前端，并按照提交学习计划逐步使用 Python 重写后端。

## 原项目简介

原项目围绕真实购物链路设计，主要角色包括：

| 角色 | 主要能力 |
| --- | --- |
| 用户 | 商品浏览、AI 导购、商品比较、购物车、下单、支付、评价 |
| 商家 | 商品管理、资料上传、订单查看、发货履约、评价回复 |
| 管理员 | 商品、订单、用户、商家、Prompt、配置、Trace 和质量测评 |

原项目重点能力包括：

- 商品、分类、商家和 SKU 管理
- AI 导购对话和 SSE 流式响应
- 商品搜索、推荐和结构化商品卡片
- 购物车、订单、支付和优惠券
- 商家运营和管理员后台
- RAG 知识检索和引用
- 图片找同款和图片向量检索
- Agent Trace、Prompt 管理和质量评测
- 风控、权限和业务状态管理

原项目的演示账号如下。这些账号属于原项目的演示数据，当前初始化版本还没有后端服务，因此暂时不能直接登录：

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | admin | admin123456 |
| 商家 | merchant | merchant123456 |
| 用户 | user | user123456 |

## 本次重构范围

本仓库专注于：

~~~text
React Web 前端
      ↓
Python FastAPI 后端
      ↓
数据库、缓存、对象存储和 Agent 能力
~~~

当前仓库不包含：

- Android 原生客户端
- Capacitor Android/iOS 工程
- 原项目后端运行代码
- 原项目运行时 Docker 编排

原项目地址仅作为产品背景和接口行为参考：

[https://github.com/LYP-leo/xzxg-shop](https://github.com/LYP-leo/xzxg-shop)


## 项目结构

~~~text
xzxg-shop-python/
├─ frontend/                 React + Vite Web 前端
├─ app/                      Python 后端包入口
├─ pyproject.toml            Python 项目元数据
├─ .env.example              环境变量模板
└─ .gitignore
~~~

## 启动 Web 前端

环境要求：

- Node.js
- npm

~~~powershell
cd frontend
npm install
npm run dev
~~~

前端通过 /api/v1 调用后端接口。后端完成后，需要保证 Python 服务提供对应的 API 地址。

## 准备 Python 后端开发环境

环境要求：

- Python 3.11+

~~~powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
~~~

当前 pyproject.toml 只保留初始化阶段的项目元数据。FastAPI、SQLAlchemy、数据库驱动和测试工具会随着后端功能提交逐步加入。


