"""Print version/bitness from a script file, avoiding native shell -c quoting."""
import platform
import struct


if __name__ == '__main__':
    print(f'{platform.python_version()}/{struct.calcsize("P") * 8}')
