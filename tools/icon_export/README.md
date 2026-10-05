# icon_export —— 从客户端 pak 抽取套装图标（官方资源）

把《鸣潮》客户端里的 `T_IconElementAttri*` 贴图导出成 `assets/echo_icons/{套装名}.png`（76×76），
供 `src/echo_icon_match.py` 做灰度 ZNCC 模板匹配。**只在换版本/补新套装时跑**，产物是仓库里的 PNG。

## 前置

| 需要 | 说明 |
|---|---|
| 客户端安装 | 含 `Client/Content/Paks/pakchunk*.pak`（本仓库开发机上实测 168 个 pak / 82.8 GB，套装图标全在 `pakchunk7`） |
| `ww-explore` | 仓库旁的 `search/ww-explore`：本工具复用它**已验证的 WuWa pak 解析**（位重排/CustomData/部分加密）与 `wuwa-keys.json`（AES key） |
| .NET SDK 10 | 跑 CUE4Parse 控制台程序（`net10.0`）；本机可 `dotnet-install.ps1 -Channel 10.0` 装到任意目录 |
| `CUE4Parse` | 仓库旁的 `search/CUE4Parse-master`（**原生支持 `GAME_WutheringWaves`**，自带 BC7Prep 解码器） |

## 三步

```powershell
# ① pak → 松散文件树（uasset/uexp；只碰需要的资产）
python tools/icon_export/pak_to_loose.py `
    --client "E:\...\Wuthering Waves (Beta) Game" `
    --ww-explore ..\search\ww-explore `
    --out .\icon_loose

# ② 松散树 → PNG（CUE4Parse）
dotnet build tools\icon_export\IconExport.csproj -c Release -p:CUE4PARSE_SKIP_NATIVE=true
dotnet tools\icon_export\bin\Release\net10.0\IconExport.dll `
    .\icon_loose 0x<wuwa-keys.json 的 mainKey> .\icon_png IconElementAttri

# ③ 按 assets/gamedata/echo_data.json 的 icon_asset 覆盖 assets/echo_icons/
python tools/icon_export/swap_icons.py --official .\icon_png --apply
```

`IconExport` 还会把 pak 内**全量文件清单**写到 `<输出目录>/pak_files.txt`（查资产路径很方便）。

## 校验（改图标后必跑）

```powershell
python tools/eval_icon_match.py     # 离线回归: 基线 219 张中 217 张高置信(99.1%), s1 中位 0.894
python -m unittest discover -s tests
```

`tests/test_gamedata.py` 会断言"每套的图标文件必须存在"，缺图直接失败。

## 四个坑（都踩过）

1. **BC7 解码走纯 C#**：`TextureDecoder.UseAssetRipperTextureDecoder = true` —— 否则要 CUE4Parse-Natives(Detex) 原生库，
   报 `Detex decompression failed: not initialized`。同时用 `-p:CUE4PARSE_SKIP_NATIVE=true` 跳过 CMake 原生构建。
2. **中文路径传参**：客户端路径含 `《鸣潮》…` 时 .NET 侧 `Directory.Exists` 会失败 → 用 ASCII 目录联接绕开
   （`cmd /c mklink /J <ascii> "<真实路径>"`）。本工具内部只在 Python 侧读路径，不受此限。
3. **pak 索引很大但很快**：只需读 footer + 目录索引；50 多个 pak 全扫一遍约 1~2 分钟。
4. **AES key 会随版本变**：从 `search/ww-explore/wuwa-keys.json` 的 `mainKey` 取，别写死在脚本里。

## 已知事实（2026-10 实测，3.7 客户端）

- 客户端有 **37 套**所需的 `T_IconElementAttri*`（另有 `IconElementAttri128_*` 128×128 版本，未使用）。
- 与历史模板逐像素对比：**29 张完全一致**（corr=1.000）、**5 张是旧版图标**（已换成官方版）、**3 张新增**（3.7 新套装）。
- **灰度孪生**：图标是"彩色圆环+白底+深色图案"，灰度 ZNCC 下有几对天生相近
  （`星构寻辉之环↔逆光跃彩之约 0.878`、`幽夜隐匿之帷↔轻云出月 0.815` —— 这两对历史模板时期就存在且线上正常；
  3.7 新图标带来 `凝夜白霜↔茜染怀想之花 0.799`）。合成帧测试已对孪生显式列白名单，真实口径以离线回归基线为准。
  若真机出现孪生误判，再考虑用环色/色相做 tie-breaker（当前刻意只用灰度）。
