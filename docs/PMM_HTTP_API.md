# 数值 PMM HTTP/1 · v2.1

此服务为 Learned-PMM / 旧版 PMM 提供真实编码、解码与训练。API-PMM 则使用其独立配置的普通 LLM API，协议见 `API_COMPATIBILITY.md`。本服务不保存另一份权威人格状态。

| model | checkpoint | 参数组织 |
| --- | --- | --- |
| `learned-pmm-v21` | `learned-pmm/2.1` | 370维输入，93字段+mask，版本化核心/Adapter |
| `learned-pmm-v2` | `learned-pmm/2` | 共享核心 θ、个体 Adapter Δ、回放和指标 |
| `pmm-mlp-v3` | `pmm/3` | v0.3 / v0.4 旧版兼容模型 |

新v21模型使用370维输入；旧v2与v3模型仍使用184维。所有模型潜变量64维，模型ID必须匹配检查点。机器可读规范为 `pmm-openapi.json`；通过 `python scripts/export_pmm_openapi.py` 从真实参数形状生成。运行示例：`python examples/pmm_http_client.py`。

## 启动、鉴权与端点

```bash
python run_pmm_service.py --port 8766
```

全部端点需要 `Authorization: Bearer <PMM_API_KEY>`。密钥至少 16 字符，可通过 `PERSONA_PMM_API_KEY` 或 `--token-file` 提供。默认只监听 `127.0.0.1:8766`。远程部署需要 HTTPS 反向代理，客户端不向远程明文 HTTP 发送数据。

| 端点 | 功能 |
| --- | --- |
| `GET /health` | 合约、模型列表、支持操作；不改变状态 |
| `GET /v1/models` | 两个数值模型标识与检查点格式 |
| `POST /v1/pmm/execute` | 无状态计算 |

执行请求示意：

```json
{
  "contract":"pmm-http/1",
  "request_id":"32位小写十六进制UUID",
  "identity_id":"当前主体32位ID",
  "model":"learned-pmm-v21",
  "checkpoint_sha256":"规范JSON的SHA256",
  "checkpoint":{"format":"learned-pmm/2"},
  "operation":"train",
  "arguments":{"epochs":30,"target":"adapter"}
}
```

示意 checkpoint 省略了必要参数，不可直接执行。使用 `LearnedPMM(identity=...).export()`、主程序导出或人格包取得完整检查点；输入特征由 `persona.pmm.vector()` 生成。

摘要为 `hashlib.sha256(json.dumps(checkpoint,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()`。这是完整性和请求关联检查，不是数字签名；跨语言实现应使用相同序列化，Python 客户端为参考实现。

## 操作

| operation | arguments | result | 返回新检查点 |
| --- | --- | --- | --- |
| encode | vectors，1–512 条向量，长度须匹配模型（370或184） | 64 维编码数组 | 否 |
| decode | x；可选 memory_vectors，最多 40 条 | 心理、风格、行动、人格/价值、语义、记忆权重；Learned 还含倾向权重/偏移与语用特征 | 否 |
| train | epochs 1–150；Learned 可选 target=adapter/core，默认 adapter | 已更新模型信息与指标 | 是 |
| rank_feedback | components 4 维 0–1，relevant 布尔 | 检索信息 | 是 |
| inspect | 空对象 | 模型信息 | 否 |

输入数值必须有限，绝对值不超过 4；请求 / 响应上限 32 MB。服务最多同时计算两个请求，超额返回 429；客户端不会自动重试。训练数据位于 checkpoint.samples，`add` 只是客户端验证与暂存，不运行梯度。

服务回传 `contract/request_id/identity_id/model/checkpoint_sha256`、`result`；写操作另有 `checkpoint/next_checkpoint_sha256`。客户端检查请求关联、主体、形状、范围、归一化、样本完整性、步数与摘要。Learned 的个体训练进一步验证核心及 core_steps 不变；核心训练验证 Adapter 参数和步数不变。未通过则丢弃候选。

主程序在副本中完成计算后，将新参数与本轮经历一起写入 SQLite；服务端不偷偷保留单独进度，不静默回退为本机计算。每次传检查点的开销适合当前小模型规模，不适合直接照搬到巨型神经网络。

## 主程序配置

```json
{
  "pmm":{
    "mode":"learned",
    "backend":"http",
    "base_url":"http://127.0.0.1:8766",
    "api_key":"你自己的服务密钥",
    "model":"learned-pmm-v21",
    "timeout":120,
    "managed":false
  }
}
```

`backend=local` 运行同一数值实现；`http` 使用独立服务。界面启动的服务设置 `managed=true`，由父进程生命周期管理。手动外部服务保持 false。切换本机/HTTP 保留精确检查点。

`train target=core` 是底层计算操作；工作台的“独立核心训练”会先建立空白 Adapter、使用当前数据训练副本、发布尚未启用的核心版本，避免把训练直接写进正在使用的主体。核心、Adapter、参数版本、人格状态和备份的管理端点见 `APP_API.md`。

对其他架构提供服务，需要扩展模型标识、检查点版本和输出校验。不能只改模型名就将任意模型当作兼容 PMM。

## Registry-PMM 固定字段

使用`persona.registry.extend_vector`生成新模型输入，勿手工重新排列。93字段顺序、registry_hash、encoder_version和state_schema_version均在`registry_contract`；VAD valence归一化为(v+1)/2，未知值槽为0且对应mask=0。未知槽非零、mask非0/1及旧长度都会被新模型拒绝。

`psychology_target`为93项0–1或null数组；null不参与监督。`view_preference`为94项归一化分布（综合基准+93字段）。decode增加`psychology_prediction`（未训练字段为null）和`registry_view_weights`，均不构成有来源的永久人格事实。核心新增F/W头，个体增加F/W残差及64×186输入条件C。

共享核心格式`pmm-core/2.1`、Adapter格式`personal-adapter/2.1`，严格校验contract及核心/主体绑定。旧检查点请先用`RegistryPMM(old_checkpoint, identity)`显式迁移再发送，不能仅更换model字符串。
