# Third-Party Notices

本项目包含从 [ok-script](https://github.com/ok-oldking/ok-script) 1.0.160 精简 vendored 的代码，
位于 `ww_engine/`。ok-script 以 MIT License 发布；以下为来源与许可声明。

## ok-script

- 项目：https://github.com/ok-oldking/ok-script
- 版本：1.0.160
- 作者：ok-oldking
- 许可：MIT License

本项目的修改说明：

- 只保留 Windows 窗口截图/键鼠注入/OCR/模板匹配/任务运行时相关模块；
- 删除 ok-script 原生 GUI、ADB/模拟器/浏览器/Genshin、更新/打包/分析/i18n 等代码；
- 将原 site-packages 的 4 处 `[ww-echo patch]` 直接合并进 vendored 代码；
- 将包名 `ok` 改为 `ww_engine`，并重写最小 `OK`/`App`/`TaskManager` 外壳；
- 详细边界见 `docs/ENGINE_VENDOR_PLAN.md`。

### MIT License

Copyright (c) ok-oldking

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
