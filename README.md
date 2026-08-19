# CATSWAR PROJECT

新的城战自动化项目。目前只保留旧项目中可靠的 ADB 基础能力，不迁移旧 V2 的界面、广告、回放或完整玩法逻辑。

## 当前框架

城战流程明确按阶段执行，任一阶段失败会停止，避免在未知界面继续点击：

```text
返回主界面 -> 进入城战 -> 扫描地图 -> 选择对手并上车 -> 战斗结束返回
```

- `actions.py`：真实 ADB 与 dry-run 动作后端，包含 `tap`、`press_back`、`wait`。
- `screen_state.py`：屏幕状态和识别标记协议；当前 `StaticScreenRecognizer` 用于测试。
- `city_war.py`：单步城战操作，包括入口、链接/建筑识别、对手选择、上车和战后返回。
- `workflow.py`：`当前步骤 + 识别状态 -> 动作 -> 下一步骤` 的流程编排。
- `run_log.py`：每次流程的 JSONL 事件日志与状态结果目录。

## 多模拟器支持

- `--instance-dir`：每台模拟器独立的截图和输出目录，也用作实例标识。
- `--cmd-dir`：多个模拟器可共享的命令目录；目前预留，尚未读取命令文件。
- 同时使用 `--capture` 和 `--instance-dir` 时，截图文件必须位于实例目录内。

## 协作边界

- 识别模块：实现 `ScreenRecognizer`，把真实截图转为 `ScreenState` 和 `Marker`。
- 坐标与规则模块：确定城战入口、建筑、连接、对手、上车和结算按钮的识别规则。
- 控制模块：通过 `CityWarController` 和 `CityWarWorkflow` 调用；设备调试时先使用 `DryRunBackend`。

## 运行

```powershell
python -m pip install -e .[dev]
python -m pytest -q
python -m catswar_project.main --discover-adb
```

```powershell
# 截图保存到实例目录。
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --instance-dir D:\runs\inst1 --capture

# 两台模拟器共用命令目录。
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --instance-dir D:\runs\inst1 --cmd-dir D:\commands
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5556 --instance-dir D:\runs\inst2 --cmd-dir D:\commands

# 单次动作，dry-run 不会操作真实设备。
python -m catswar_project.main --dry-run --tap 100 200
```

真实设备操作需要同时提供 `--adb-path` 和 `--adb-serial`。工作流日志默认写入 `output/runs/<run-id>/`，该目录不提交。
