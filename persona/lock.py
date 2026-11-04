"""One writer process per data directory (Windows and Unix)."""
from pathlib import Path
import os
class InstanceLock:
    def __init__(self,directory):self.directory=Path(directory);self.file=None
    def __enter__(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        self.file=open(self.directory/'runtime.lock','a+b')
        self.file.seek(0);self.file.write(b'1');self.file.flush();self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('这位主体已经在另一个程序中运行。请关闭旧窗口或使用不同的数据目录。') from None
        return self
    def __exit__(self,*args):
        if self.file:self.file.close()
