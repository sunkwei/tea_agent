#!/usr/bin/env python3
"""Debug script to see what bytes Konsole sends for arrow keys."""
import sys, select, tty, termios, os, time

def debug_keys():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        print("=== Arrow Key Debug ===")
        print("Press ↑ ↓ ← →  (or 'q' to quit)")
        print("Raw bytes will be shown in hex and repr")
        print("=" * 40)
        
        while True:
            if select.select([sys.stdin], [], [], 1)[0]:
                ch = os.read(fd, 1)
                if ch == b'q':
                    break
                
                # Check if this might be the start of an escape sequence
                if ch == b'\x1b':
                    # Wait a tiny bit for more bytes
                    time.sleep(0.05)
                    rest = b''
                    while select.select([sys.stdin], [], [], 0)[0]:
                        rest += os.read(fd, 1)
                    
                    if rest:
                        print(f"ESC sequence: {ch.hex()} + {rest.hex()} = {ch + rest}")
                        # Show as hex bytes individual
                        seq = ch + rest
                        parts = ' '.join(f'\\x{b:02x}' for b in seq)
                        print(f"  repr: {seq!r}")
                        print(f"  bytes: {parts}")
                        
                        # Decode arrow keys
                        if rest == b'[A' or rest == b'OA':
                            print(f"  >>> UP ARROW <<<")
                        elif rest == b'[B' or rest == b'OB':
                            print(f"  >>> DOWN ARROW <<<")
                        elif rest == b'[D' or rest == b'OD':
                            print(f"  >>> LEFT ARROW <<<")
                        elif rest == b'[C' or rest == b'OC':
                            print(f"  >>> RIGHT ARROW <<<")
                        else:
                            print(f"  >>> Unknown escape sequence <<<")
                    else:
                        print(f"ESC alone (no following bytes)")
                else:
                    print(f"Char: {ch.hex()} = {ch!r} = {ch}")
            else:
                print("(waiting for key...)")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print("\nDone.")

if __name__ == '__main__':
    debug_keys()
