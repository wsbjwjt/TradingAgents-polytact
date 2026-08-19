"""支持 `python -m studio`（等价于 studio 命令，便于脚本跨环境调用）。"""

from studio.cli import main

if __name__ == "__main__":
    main()
