# 倒易晶格审计台（Diffraction Lattice Audit）

从电子衍射图提取的整数像素斑点中，用**精确整数运算**找出最粗的整数仿射晶格：
先最少化离群点数，再最大化基矩阵行列式绝对值（晶胞面积），
再以离群标识序列、规范 Hermite 标准形依次裁决。后端返回基矩阵、
规范余类原点以及每个保留点的整数坐标，全部可独立复算。

## 目录结构

```
backend/            FastAPI 服务（精确整数求解器）
  app/exact_json.py 任意精度整数的精确 JSON 边界（标签整数，禁止裸数字）
  app/lattice.py    HNF / 扩展欧几里得 / 余类原点 / 逐点整数坐标（纯整数）
  app/solver.py     枚举删除 0..K 个点的生成格，按裁决次序求最优
  app/main.py       /health 与 POST /api/audit
  tests/            纯标准库测试（含对拍独立全枚举的最优性验证、边界编解码）
  scripts/acceptance.py  compose verify 一次性验收脚本（含真实浏览器回归）
frontend/           React + Vite 单页应用（SVG 晶格叠加）
  src/exact.js      业务整数的十进制字符串表示与标签整数编解码
  src/LatticeOverlay.jsx 仅在 SVG 投影边界使用有限精度浮点
docker-compose.yml  backend + web + 一次性 verify 服务
```

## 运行

```bash
# 构建并启动（前端宿主机端口可用 FRONTEND_PORT 覆盖，默认 8080）
docker compose up -d --build

# 浏览器打开 http://localhost:8080
# 后端接口文档 http://localhost:8000 仅在容器网络内；通过 web 反代访问：
#   GET  http://localhost:8080/health
#   POST http://localhost:8080/api/audit
FRONTEND_PORT=9000 docker compose up -d   # 自定义宿主机端口
```

健康检查：`backend` 与 `web` 均在 Dockerfile 中声明 HEALTHCHECK；
web 的健康检查经 nginx 反代打到后端 `/health`。

## 一次性验收服务

`verify` 服务启动后自行退出，**以退出码报告结果**（0 通过，非 0 失败）：

```bash
docker compose build verify
docker compose run verify        # 退出码即验收结论
# 或随栈一起启动后查看：
docker compose up --build verify
docker inspect -f '{{.State.ExitCode}}' lattice-audit-verify
```

验收内容：精确整数单元测试（lattice + 边界编解码）→ 后端 HTTP 健康 →
nginx 静态页与反代 → 污染网格场景（面积 12、恰 3 个离群点 b0/b1/b2）→
代理同请求结论一致 → 不可行时的最大面积见证可复算 → 输入契约 422（含拒绝
裸 JSON 数字）→ 10^18 坐标精确性 → **真实无头 Chromium 打开页面、填入
超过 2^53 的相邻整数坐标并点击「执行审计」**，断言发出的请求保留 6 个互异
坐标、页面逐值显示精确的面积/基/原点/逐点坐标 → 旧缺陷探针输出
`NOT_REPRODUCED`。verify 镜像（`backend/Dockerfile.verify`）内置 Chromium。

## 接口

`POST /api/audit`

JavaScript `Number` 无法区分超过 `2**53` 的相邻整数（例如
`9007199254740992/3/4` 经 `JSON.parse` 后会丢精度），因此接口的**每个
整数字段**（坐标、参数、面积、基、原点、逐点坐标等）都以标签整数
`{"@type": "int", "value": "<十进制数字串>"}` 传输；后端拒绝任何裸 JSON
数字，响应中的整数同样带标签，布尔值（`feasible`）与字符串保持原生 JSON。

请求体（示意）：

```json
{
  "points": [{"id": "g0",
              "x": {"@type": "int", "value": "-4"},
              "y": {"@type": "int", "value": "0"}}],
  "min_cell_area": {"@type": "int", "value": "12"},
  "max_outliers": {"@type": "int", "value": "3"}
}
```

契约（解码为 Python 整数后）：

- 6–60 个点；`id` 非空字符串且唯一；`x,y` 为整数且坐标不重复；
  `min_cell_area ∈ [2, 10^6]`；`max_outliers ∈ [0,3]`。
- 成功：`feasible=true`，`result` 含列向量基 `basis.b1/b2`（HNF）、
  规范余类原点 `origin`、`area`、每个保留点的整数坐标 `coord=(m,n)`
  （满足 `p == origin + m*b1 + n*b2`）以及排序后的离群标识。
- 失败：`feasible=false`，原样回显 `input`，并给出上限内**可核验的
  最大面积见证** `witness`（同样含基、原点与逐点整数坐标）。

任何候选至少保留三个不共线点；否则被拒绝。

## 正确性要点

- 任意保留点集 `T` 的**生成格**（基点加所有差向量的 Z-张成，HNF 由
  2×2 子式 gcd 决定）是包含 `T` 的最小格，即面积最大的格；因此最优解必为
  删除至多 K 个点后某个剩余集的生成格。枚举全部 `Σ C(n,k) (k≤3)` 删除集
  （n=60 时 34,221 个）即完备无遗漏。
- 全部运算为 Python 任意精度整数（HNF、扩展 gcd、整除判定、余类原点
  规范化），坐标 10^18、面积 10^36 亦精确。
- 前端在输入、唯一性比较、请求构造、响应解析与结果展示全链路把业务整数
  保存为十进制字符串（标签整数过线），不经过 `Number`；浮点只在 SVG
  投影边界出现（`toFinite`），且不会回写业务数据。若互异精确点在该尺度
  投影重合或网格过密，图上给出提示，精确值仍以下方表格为准。
- 前端在成功审计后若修改任意点（含离群点）或参数，旧图与旧结论立即失效
  （签名比对 + 置顶提示），必须重新审计后才显示新结果。

## 本地开发（无 Docker）

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn app.main:app --port 8000
# 前端
cd frontend && npm install && npm run dev   # vite 已配置 /api、/health 代理
```
