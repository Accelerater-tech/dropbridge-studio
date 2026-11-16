"""打包入口：PyInstaller 不能直接跑 app/main.py（相对导入会失败）。"""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
