# Desktop GUI

The project includes a Windows Tkinter front end. It reuses the same scheduler
and state-driven automation as the command-line runner.

## Start from the source checkout

```powershell
uv run catswar gui
```

Or double-click `start_gui.cmd`.

## Start from the release package

1. Run `install.cmd` once.
2. Edit the account rows and OmniParser address in the window.
3. Click `检查 ADB` and confirm the target serial has state `device`.
4. Click `保存`, then `启动自动化`.

Use `guarded` mode for the first run. The `停止` button writes the configured
stop file and lets the current safe action finish. Logs, screenshots, and
checkpoints remain under the configured output directory.

When OmniParser runs on another computer, use that computer's LAN address in
the URL, for example `http://192.168.1.20:8000/parse/`, and allow the port
through its firewall.
